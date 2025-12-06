import { FormEvent, useCallback, useState } from "react";
import { searchImdbTitles } from "./api";
import { ImdbTitle } from "./types";

type SearchResult = {
  id: string;
  title: string;
  image: string | null;
  rating: number | null;
  year: number | null;
  type: string | null;
};

const normalizeResults = (items: ImdbTitle[]): SearchResult[] =>
  items.map((item, index) => {
    const fallbackId = `local-${index}-${Date.now().toString(36)}`;
    const id = item.id ?? item.url?.match(/tt\d+/)?.[0] ?? fallbackId;
    return {
      id,
      title: item.title ?? "Untitled",
      image: item.image ?? null,
      rating: item.rating ?? null,
      year: item.year ?? null,
      type: item.type ?? null,
    };
  });

export default function App() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSearch = useCallback(
    async (text?: string) => {
      const nextQuery = (text ?? query).trim();
      if (!nextQuery) {
        setResults([]);
        return;
      }
      setIsSearching(true);
      setError(null);
      try {
        const response = await searchImdbTitles(nextQuery, 20);
        setResults(normalizeResults(response));
      } catch (err) {
        setError((err as Error).message);
        setResults([]);
      } finally {
        setIsSearching(false);
      }
    },
    [query]
  );

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void handleSearch();
  };

  const formatType = (value: string | null): string => {
    if (!value) {
      return "Unknown type";
    }
    const spaced = value
      .replace(/_/g, " ")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .toLowerCase();
    return spaced.replace(/\b\w/g, (char) => char.toUpperCase());
  };

  return (
    <div className="layout">
      <header>
        <h1>DSRPFlix </h1>
        <p className="muted">
          Curso de Machine Learning 4
        </p>
      </header>

      <main>
        <section className="panel">
          <h2>¿No sabes qué ver?</h2>
          <form className="search-form" onSubmit={onSubmit}>
            <input
              type="text"
              placeholder="Explicame qué tienes en mente y yo te daré mi mejor recomendación..."
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
            <button type="submit" disabled={!query.trim() || isSearching}>
              {isSearching ? "Searching..." : "Search"}
            </button>
          </form>
          {error && <p className="muted error">{error}</p>}
        </section>

        <section className="panel">
          <div className="panel-header">
            <h2>Te sugiero ver...</h2>
            {isSearching && <span className="badge">Loading…</span>}
          </div>
          {results.length === 0 && !isSearching ? (
            <p className="empty-state">
              Use the search bar above to fetch the top recommendations.
            </p>
          ) : (
            <div className="grid results-grid">
              {results.map((item) => (
                <article className="card result-card" key={item.id}>
                  {item.image ? (
                    <img src={item.image} alt={`${item.title} poster`} loading="lazy" />
                  ) : (
                    <div className="placeholder">
                      <span>No image</span>
                    </div>
                  )}
                  <div className="card-content">
                    <h3>{item.title}</h3>
                    <div className="card-meta">
                      <span className="chip chip-type">{formatType(item.type)}</span>
                      <span className="chip chip-year">{item.year ?? "Año por confirmar"}</span>
                    </div>
                    <div className="card-footer">
                      <span className="rating-badge">
                        <span className="rating-value">
                          {item.rating != null ? item.rating.toFixed(1) : "N/A"}
                        </span>
                        <span className="rating-label">IMDb</span>
                      </span>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </main>

      <footer>
        Data Science Research Peru - Curso MLOps
      </footer>
    </div>
  );
}
