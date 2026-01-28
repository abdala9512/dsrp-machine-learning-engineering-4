"""Service layer for ML and IMDB API calls."""

import asyncio
import logging
from typing import Optional

import httpx

from config import Settings
from schemas import MovieResult, MLServiceResponse

logger = logging.getLogger(__name__)


class MLServiceClient:
    """Client for the ML recommendation service."""

    def __init__(self, settings: Settings):
        self.base_url = settings.ml_service_url.rstrip("/")
        self.timeout = settings.ml_service_timeout

    async def search(
        self, query: str, top_k: int = 10
    ) -> tuple[list[dict], list[str]]:
        """
        Call ML service to get movie recommendations.

        Returns:
            Tuple of (full results with scores, list of movie IDs)
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/predict",
                    json={"query": query, "top_k": top_k},
                )
                response.raise_for_status()
                data = response.json()

                results = data.get("results", [])
                movie_ids = data.get("movie_ids", [])

                logger.info(f"ML service returned {len(movie_ids)} results for query: {query}")
                return results, movie_ids

            except httpx.TimeoutException:
                logger.error(f"ML service timeout for query: {query}")
                raise
            except httpx.HTTPStatusError as e:
                logger.error(f"ML service HTTP error: {e.response.status_code}")
                raise
            except Exception as e:
                logger.error(f"ML service error: {e}")
                raise

    async def health_check(self) -> bool:
        """Check if ML service is healthy."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
            except Exception:
                return False


class IMDBApiClient:
    """Client for the IMDB API."""

    def __init__(self, settings: Settings):
        self.base_url = settings.imdb_api_url.rstrip("/")
        self.timeout = settings.imdb_api_timeout

    async def get_movie_by_id(self, movie_id: str) -> Optional[dict]:
        """Fetch movie details by IMDB ID."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Try the titles endpoint
                response = await client.get(
                    f"{self.base_url}/titles/{movie_id}",
                    headers={"accept": "application/json"},
                )

                if response.status_code == 200:
                    return response.json()

                logger.warning(f"IMDB API returned {response.status_code} for {movie_id}")
                return None

            except Exception as e:
                logger.error(f"IMDB API error for {movie_id}: {e}")
                return None

    async def get_movies_by_ids(
        self, movie_ids: list[str], ml_results: Optional[list[dict]] = None
    ) -> list[MovieResult]:
        """
        Fetch multiple movies by their IMDB IDs concurrently.

        Args:
            movie_ids: List of IMDB IDs (e.g., ['tt0468569', 'tt1345836'])
            ml_results: Optional ML results to merge scores from

        Returns:
            List of MovieResult with IMDB details and ML scores
        """
        # Create a mapping of movie_id -> ml_result for score lookup
        ml_scores = {}
        if ml_results:
            for result in ml_results:
                imdb_id = result.get("imdb_id")
                if imdb_id:
                    ml_scores[imdb_id] = result

        # Fetch all movies concurrently
        tasks = [self.get_movie_by_id(movie_id) for movie_id in movie_ids]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for movie_id, response in zip(movie_ids, responses):
            if isinstance(response, Exception):
                logger.error(f"Error fetching {movie_id}: {response}")
                continue

            if response is None:
                continue

            # Extract movie data from IMDB response
            movie = self._parse_imdb_response(movie_id, response)

            # Merge ML scores if available
            if movie_id in ml_scores:
                ml_data = ml_scores[movie_id]
                movie.ltr_score = ml_data.get("ltr_score")
                movie.retrieval_score = ml_data.get("retrieval_score")
                movie.sim_embedding = ml_data.get("sim_embedding")

            results.append(movie)

        return results

    def _parse_imdb_response(self, movie_id: str, data: dict) -> MovieResult:
        """Parse IMDB API response into MovieResult."""
        # Handle various response formats
        rating_data = data.get("rating", {})
        if isinstance(rating_data, dict):
            rating = rating_data.get("aggregateRating")
            votes = rating_data.get("voteCount")
        else:
            rating = data.get("rating")
            votes = data.get("ratingVotes")

        # Get image URL
        image_data = data.get("primaryImage", {})
        if isinstance(image_data, dict):
            image = image_data.get("url")
        else:
            image = data.get("image") or data.get("poster")

        return MovieResult(
            id=movie_id,
            title=data.get("primaryTitle") or data.get("title") or "Unknown",
            url=f"https://www.imdb.com/title/{movie_id}/",
            year=data.get("startYear") or data.get("year"),
            image=image,
            rating=rating,
            ratingVotes=votes,
            type=data.get("titleType") or data.get("type"),
        )

    async def search_titles(self, query: str, limit: int = 20) -> list[MovieResult]:
        """Search IMDB directly (fallback when ML service is disabled)."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Try different endpoint variations
                endpoints = [
                    f"{self.base_url}/search/titles?query={query}&limit={limit}",
                    f"{self.base_url}/search/titles?q={query}&limit={limit}",
                    f"{self.base_url}/search?q={query}&limit={limit}",
                ]

                for endpoint in endpoints:
                    try:
                        response = await client.get(
                            endpoint,
                            headers={"accept": "application/json"},
                        )
                        if response.status_code == 200:
                            data = response.json()
                            return self._parse_search_response(data)
                    except Exception:
                        continue

                logger.warning(f"All IMDB search endpoints failed for query: {query}")
                return []

            except Exception as e:
                logger.error(f"IMDB search error: {e}")
                return []

    def _parse_search_response(self, data: dict) -> list[MovieResult]:
        """Parse IMDB search response."""
        # Find the results array in various possible locations
        results = None
        for key in ["titles", "results", "items", "data"]:
            if key in data:
                results = data[key]
                if isinstance(results, dict):
                    results = results.get("titles", [])
                break

        if not results or not isinstance(results, list):
            return []

        movies = []
        for item in results:
            if not isinstance(item, dict):
                continue

            movie_id = item.get("id") or item.get("imdbId") or item.get("tconst")
            if not movie_id:
                continue

            movies.append(
                MovieResult(
                    id=movie_id,
                    title=item.get("title") or item.get("primaryTitle") or "Unknown",
                    url=item.get("url"),
                    year=item.get("year") or item.get("startYear"),
                    image=item.get("image") or item.get("poster"),
                    rating=self._extract_rating(item),
                    ratingVotes=self._extract_votes(item),
                    type=item.get("type") or item.get("titleType"),
                )
            )

        return movies

    def _extract_rating(self, item: dict) -> Optional[float]:
        """Extract rating from various field formats."""
        for key in ["rating", "imdbRating", "aggregateRating"]:
            val = item.get(key)
            if val is not None:
                if isinstance(val, dict):
                    val = val.get("aggregateRating") or val.get("ratingValue")
                if val is not None:
                    try:
                        return float(val)
                    except (ValueError, TypeError):
                        pass
        return None

    def _extract_votes(self, item: dict) -> Optional[int]:
        """Extract vote count from various field formats."""
        for key in ["ratingVotes", "voteCount", "numVotes"]:
            val = item.get(key)
            if val is not None:
                if isinstance(val, str):
                    val = val.replace(",", "")
                try:
                    return int(val)
                except (ValueError, TypeError):
                    pass
        return None

    async def health_check(self) -> bool:
        """Check if IMDB API is reachable."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                response = await client.get(f"{self.base_url}/titles/tt0468569")
                return response.status_code == 200
            except Exception:
                return False
