import { ImdbSearchResponse, ImdbTitle } from "./types";

const resolveApiBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_IMDB_API_BASE_URL as string | undefined;
  const defaultUrl = "https://api.imdbapi.dev";
  const base = envUrl?.trim() || defaultUrl;
  return base.endsWith("/") ? base.slice(0, -1) : base;
};

const normalizeRating = (item: Record<string, unknown>): number | null => {
  const candidates = [
    item.rating,
    item.imDbRating,
    item.averageRating,
    item.ratingValue,
    (item.ratingsSummary as { aggregateRating?: number } | undefined)?.aggregateRating,
    (item.titleRating as { rating?: number } | undefined)?.rating,
    (item.rating as { aggregateRating?: number; rating?: number } | undefined),
  ];
  for (const candidate of candidates) {
    if (candidate == null) continue;
    if (typeof candidate === "object") {
      const fields = candidate as Record<string, unknown>;
      const agg = fields.aggregateRating ?? fields.rating ?? fields.score ?? fields.value;
      if (agg != null) {
        const value =
          typeof agg === "string" ? Number(agg) : typeof agg === "number" ? agg : Number(agg);
        if (!Number.isNaN(value)) {
          return value;
        }
      }
      continue;
    }
    const parsed = typeof candidate === "string" ? Number(candidate) : Number(candidate);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return null;
};

const normalizeVotes = (item: Record<string, unknown>): number | null => {
  const candidates = [
    item.ratingVotes,
    item.ratingcount,
    item.ratings,
    (item.ratingsSummary as { voteCount?: number } | undefined)?.voteCount,
    (item.titleRating as { voteCount?: number } | undefined)?.voteCount,
    (item.primaryRatingsSummary as { voteCount?: number } | undefined)?.voteCount,
    (item.rating as { voteCount?: number } | undefined),
  ];
  for (const candidate of candidates) {
    if (candidate == null) continue;
    if (typeof candidate === "object") {
      const fields = candidate as Record<string, unknown>;
      const count = fields.voteCount ?? fields.votes;
      if (count != null) {
        const sanitized =
          typeof count === "string" ? count.replace(/,/g, "").trim() : count;
        const value =
          typeof sanitized === "string" ? Number(sanitized) : Number(sanitized);
        if (!Number.isNaN(value)) {
          return value;
        }
      }
      continue;
    }
    const sanitized =
      typeof candidate === "string" ? candidate.replace(/,/g, "").trim() : candidate;
    const value = typeof sanitized === "string" ? Number(sanitized) : Number(sanitized);
    if (!Number.isNaN(value)) {
      return value;
    }
  }
  return null;
};

const tryParseYear = (value: unknown): number | null => {
  if (typeof value === "number") {
    return Number.isNaN(value) ? null : value;
  }
  if (typeof value === "string") {
    const match = value.match(/\d{4}/);
    if (match) {
      const parsed = Number(match[0]);
      if (!Number.isNaN(parsed)) {
        return parsed;
      }
    }
  }
  if (value && typeof value === "object") {
    const maybeYear = (value as { year?: unknown; endYear?: unknown }).year;
    if (maybeYear != null) {
      return tryParseYear(maybeYear);
    }
  }
  return null;
};

const findFirstArray = (node: unknown): ImdbTitle[] | null => {
  if (Array.isArray(node)) {
    return node as ImdbTitle[];
  }
  if (node && typeof node === "object") {
    for (const value of Object.values(node as Record<string, unknown>)) {
      const found = findFirstArray(value);
      if (found) {
        return found;
      }
    }
  }
  return null;
};

const unwrapTitle = (item: Record<string, unknown>): Record<string, unknown> => {
  const visited = new Set<Record<string, unknown>>();
  let current: Record<string, unknown> | null = item;

  while (current && typeof current === "object") {
    if (visited.has(current)) {
      break;
    }
    visited.add(current);

    if (current.title && typeof current.title === "object") {
      current = current.title as Record<string, unknown>;
      continue;
    }

    if (current.node && typeof current.node === "object") {
      current = current.node as Record<string, unknown>;
      continue;
    }

    if (current.entity && typeof current.entity === "object") {
      current = current.entity as Record<string, unknown>;
      continue;
    }

    if (current.primaryTitle && typeof current.primaryTitle === "object") {
      current = current.primaryTitle as Record<string, unknown>;
      continue;
    }

    break;
  }

  return current ?? item;
};

const resolveType = (value: unknown): string | null => {
  if (typeof value === "string") {
    return value;
  }
  if (value && typeof value === "object") {
    const record = value as {
      text?: unknown;
      value?: unknown;
      id?: unknown;
      name?: unknown;
      category?: unknown;
    };
    const candidate = record.text ?? record.value ?? record.id ?? record.name ?? record.category;
    if (typeof candidate === "string") {
      return candidate;
    }
  }
  return null;
};

const normalizeList = (rawList: ImdbTitle[], limit: number): ImdbTitle[] => {
  return rawList
    .map((item) => {
      const mutableItem = item as Record<string, unknown>;
      const core = unwrapTitle(mutableItem);
      const rating = normalizeRating(core);
      const votes = normalizeVotes(core);
      const derivedId =
        (core.id as string | undefined) ||
        (item.id as string | undefined) ||
        (typeof core["titleId"] === "string" ? (core["titleId"] as string) : undefined) ||
        (typeof mutableItem["imdb_id"] === "string"
          ? (mutableItem["imdb_id"] as string)
          : undefined) ||
        (typeof core["tconst"] === "string" ? (core["tconst"] as string) : undefined) ||
        (typeof core.url === "string" ? core.url.match(/tt\d+/)?.[0] ?? "" : "") ||
        (typeof item.url === "string" ? item.url.match(/tt\d+/)?.[0] ?? "" : "");
      const title =
        (core.title as string | undefined) ||
        (item.title as string | undefined) ||
        (mutableItem["titleText"] as { text?: string } | undefined)?.text ||
        (core["titleText"] as { text?: string } | undefined)?.text ||
        (item.name as string | undefined) ||
        (mutableItem["nameText"] as { text?: string } | undefined)?.text ||
        (mutableItem["originalTitleText"] as { text?: string } | undefined)?.text ||
        (core["originalTitleText"] as { text?: string } | undefined)?.text ||
        (mutableItem["primaryTitle"] as string | undefined) ||
        (core["primaryTitle"] as string | undefined) ||
        "Untitled";
      const image =
        (core.image as string | undefined) ||
        (item.image as string | undefined) ||
        (mutableItem["primaryImage"] as { url?: string } | undefined)?.url ||
        (core["primaryImage"] as { url?: string } | undefined)?.url ||
        (mutableItem["imageUrl"] as string | undefined) ||
        (core["imageUrl"] as string | undefined) ||
        null;
      const year =
        tryParseYear(core["year"]) ??
        tryParseYear(item.year) ??
        tryParseYear(core["releaseYear"]) ??
        tryParseYear(mutableItem["releaseYear"]) ??
        tryParseYear(core["titleReleaseInfo"]) ??
        tryParseYear(core["startYear"]) ??
        tryParseYear(mutableItem["startYear"]) ??
        tryParseYear((core["releaseDate"] as { year?: unknown } | undefined)?.year) ??
        tryParseYear((mutableItem["releaseDate"] as { year?: unknown } | undefined)?.year) ??
        tryParseYear(
          (core["titleReleaseInfo"] as { releaseYear?: unknown } | undefined)?.releaseYear
        ) ??
        tryParseYear(
          (mutableItem["titleReleaseInfo"] as { releaseYear?: unknown } | undefined)?.releaseYear
        ) ??
        null;
      const type =
        resolveType(core["type"]) ??
        resolveType(item.type) ??
        resolveType(mutableItem["type"]) ??
        resolveType(core["titleType"]) ??
        resolveType(mutableItem["titleType"]) ??
        resolveType(core["titleCategory"]) ??
        null;

      return {
        id: derivedId,
        title,
        url: (core.url as string | undefined) ?? (item.url as string | undefined) ?? null,
        year,
        image,
        rating,
        ratingVotes: votes,
        type,
      };
    })
    .filter((item) => item.id)
    .sort((a, b) => {
      const ratingA = a.rating ?? 0;
      const ratingB = b.rating ?? 0;
      if (ratingA === ratingB) {
        const votesA = a.ratingVotes ?? 0;
        const votesB = b.ratingVotes ?? 0;
        return votesB - votesA;
      }
      return ratingB - ratingA;
    })
    .slice(0, limit);
};

export async function searchImdbTitles(query: string, limit = 20): Promise<ImdbTitle[]> {
  const baseUrl = resolveApiBaseUrl();
  const endpoints = [
    { path: "/search/titles", params: { query, limit: limit.toString() } },
    { path: "/search/titles", params: { q: query, limit: limit.toString() } },
    { path: "/search", params: { q: query, limit: limit.toString() } },
  ];

  let lastError: Error | null = null;

  for (const endpoint of endpoints) {
    const params = new URLSearchParams(endpoint.params);
    const response = await fetch(`${baseUrl}${endpoint.path}?${params.toString()}`, {
      headers: {
        Accept: "application/json",
      },
    });

    if (!response.ok) {
      lastError = new Error((await response.text()) || `IMDb API error (${response.status})`);
      continue;
    }

    const payload = (await response.json()) as ImdbSearchResponse | Record<string, unknown>;
    const list = findFirstArray(payload);
    if (Array.isArray(list) && list.length > 0) {
      return normalizeList(list, limit);
    }
  }

  if (lastError) {
    throw lastError;
  }

  throw new Error("IMDb API did not return any results.");
}
