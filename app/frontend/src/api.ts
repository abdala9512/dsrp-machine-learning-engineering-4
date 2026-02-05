import { ImdbTitle } from "./types";

const resolveBackendUrl = (): string => {
  const envUrl = import.meta.env.VITE_BACKEND_URL as string | undefined;
  const defaultUrl = "http://localhost:8080";
  const base = envUrl?.trim() || defaultUrl;
  return base.endsWith("/") ? base.slice(0, -1) : base;
};

interface BackendSearchResponse {
  query: string;
  results: Array<{
    id: string;
    title: string;
    url?: string | null;
    year?: number | null;
    image?: string | null;
    rating?: number | null;
    ratingVotes?: number | null;
    type?: string | null;
    ltr_score?: number | null;
    retrieval_score?: number | null;
    sim_embedding?: number | null;
  }>;
  count: number;
  source: "ml" | "imdb";
}

export async function searchImdbTitles(query: string, limit = 20, useML = true): Promise<ImdbTitle[]> {
  const backendUrl = resolveBackendUrl();

  const response = await fetch(`${backendUrl}/search`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({
      query,
      limit,
      use_ml: useML,
    }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `Backend API error (${response.status})`);
  }

  const data = (await response.json()) as BackendSearchResponse;

  return data.results.map((item) => ({
    id: item.id,
    title: item.title,
    url: item.url,
    year: item.year,
    image: item.image,
    rating: item.rating,
    ratingVotes: item.ratingVotes,
    type: item.type,
  }));
}
