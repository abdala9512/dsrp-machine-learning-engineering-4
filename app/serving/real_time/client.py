#!/usr/bin/env python
"""
Load testing client for the Movie Recommendation API.

Sends multiple queries to the API and displays performance statistics.
Metrics are automatically captured by the API's Prometheus endpoint.
"""

import argparse
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import httpx

# Sample queries for testing
SAMPLE_QUERIES = [
    "action movies similar to the dark knight",
    "romantic comedies from the 90s",
    "sci-fi movies about time travel",
    "horror movies with good plot twists",
    "animated movies for kids",
    "thriller movies like gone girl",
    "war movies based on true stories",
    "comedy movies with will ferrell",
    "drama movies about family",
    "adventure movies like indiana jones",
    "mystery movies with unexpected endings",
    "superhero movies from marvel",
    "classic movies from the 80s",
    "foreign films with subtitles",
    "documentaries about nature",
    "musicals with great soundtracks",
    "sports movies about underdog teams",
    "crime movies like the godfather",
    "fantasy movies with dragons",
    "biographical movies about musicians",
    "movies similar to inception",
    "feel good movies for a rainy day",
    "movies with strong female leads",
    "movies set in new york city",
    "movies about artificial intelligence",
    "psychological thrillers",
    "movies based on books",
    "indie films from sundance",
    "movies with plot twists",
    "movies about space exploration",
]


@dataclass
class RequestResult:
    """Result of a single API request."""

    query: str
    status_code: int
    latency_ms: float
    movie_count: int
    success: bool
    error: str | None = None


def send_request(
    client: httpx.Client,
    base_url: str,
    query: str,
    top_k: int = 10,
) -> RequestResult:
    """Send a single request to the API."""
    start_time = time.perf_counter()

    try:
        response = client.post(
            f"{base_url}/predict",
            json={"query": query, "top_k": top_k},
            timeout=30.0,
        )
        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code == 200:
            data = response.json()
            return RequestResult(
                query=query,
                status_code=response.status_code,
                latency_ms=latency_ms,
                movie_count=data.get("count", 0),
                success=True,
            )
        else:
            return RequestResult(
                query=query,
                status_code=response.status_code,
                latency_ms=latency_ms,
                movie_count=0,
                success=False,
                error=response.text[:200],
            )

    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        return RequestResult(
            query=query,
            status_code=0,
            latency_ms=latency_ms,
            movie_count=0,
            success=False,
            error=str(e)[:200],
        )


def run_load_test(
    base_url: str,
    num_requests: int,
    concurrency: int,
    top_k: int,
) -> tuple[list[RequestResult], float]:
    """Run load test with concurrent requests."""
    results: list[RequestResult] = []

    # Generate queries (cycle through sample queries)
    queries = [random.choice(SAMPLE_QUERIES) for _ in range(num_requests)]

    print(f"\n{'='*60}")
    print("Load Test Configuration")
    print(f"{'='*60}")
    print(f"  Target URL: {base_url}")
    print(f"  Total Requests: {num_requests}")
    print(f"  Concurrency: {concurrency}")
    print(f"  Top K: {top_k}")
    print(f"{'='*60}\n")

    start_time = time.perf_counter()

    with httpx.Client() as client:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {
                executor.submit(send_request, client, base_url, query, top_k): query
                for query in queries
            }

            completed = 0
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                completed += 1

                # Progress indicator
                if completed % 100 == 0 or completed == num_requests:
                    pct = (completed / num_requests) * 100
                    print(f"  Progress: {completed}/{num_requests} ({pct:.1f}%)")

    total_time = time.perf_counter() - start_time

    return results, total_time


def print_statistics(results: list[RequestResult], total_time: float) -> None:
    """Print test statistics."""
    successful = [r for r in results if r.success]
    failed = [r for r in results if not r.success]

    latencies = [r.latency_ms for r in successful]

    print(f"\n{'='*60}")
    print("Load Test Results")
    print(f"{'='*60}")

    # Summary
    print("\n  Summary:")
    print(f"    Total Requests: {len(results)}")
    print(f"    Successful: {len(successful)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"    Failed: {len(failed)} ({len(failed)/len(results)*100:.1f}%)")
    print(f"    Total Time: {total_time:.2f}s")
    print(f"    Requests/sec: {len(results)/total_time:.2f}")

    if latencies:
        latencies.sort()
        print("\n  Latency (ms):")
        print(f"    Min: {min(latencies):.2f}")
        print(f"    Max: {max(latencies):.2f}")
        print(f"    Mean: {sum(latencies)/len(latencies):.2f}")
        print(f"    P50: {latencies[len(latencies)//2]:.2f}")
        print(f"    P90: {latencies[int(len(latencies)*0.9)]:.2f}")
        print(f"    P95: {latencies[int(len(latencies)*0.95)]:.2f}")
        print(f"    P99: {latencies[int(len(latencies)*0.99)]:.2f}")

    if failed:
        print("\n  Errors:")
        error_counts: dict[str, int] = {}
        for r in failed:
            error_key = r.error[:50] if r.error else "Unknown"
            error_counts[error_key] = error_counts.get(error_key, 0) + 1

        for error, count in sorted(error_counts.items(), key=lambda x: -x[1])[:5]:
            print(f"    [{count}x] {error}")

    print(f"\n{'='*60}")
    print("  Metrics available at: http://localhost:8000/metrics")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Load testing client for Movie Recommendation API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run 100 requests with 10 concurrent workers
  python client.py -n 100 -c 10

  # Run 1000 requests with 50 concurrent workers
  python client.py -n 1000 -c 50

  # Custom API URL
  python client.py -n 100 --url http://movie-api:8000
        """,
    )

    parser.add_argument(
        "-n",
        "--num-requests",
        type=int,
        default=100,
        help="Number of requests to send (default: 100)",
    )
    parser.add_argument(
        "-c",
        "--concurrency",
        type=int,
        default=10,
        help="Number of concurrent workers (default: 10)",
    )
    parser.add_argument(
        "-k",
        "--top-k",
        type=int,
        default=10,
        help="Top K results per request (default: 10)",
    )
    parser.add_argument(
        "--url",
        type=str,
        default="http://localhost:8000",
        help="API base URL (default: http://localhost:8000)",
    )

    args = parser.parse_args()

    # Run load test
    results, total_time = run_load_test(
        base_url=args.url,
        num_requests=args.num_requests,
        concurrency=args.concurrency,
        top_k=args.top_k,
    )

    # Print statistics
    print_statistics(results, total_time)


if __name__ == "__main__":
    main()
