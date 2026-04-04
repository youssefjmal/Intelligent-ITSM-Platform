/**
 * Global search API client.
 * Used by the search bar in the app shell.
 */

export interface SearchResultItem {
  id: string;
  type: "ticket" | "problem" | "kb";
  title: string;
  excerpt: string;
  status: string | null;
  priority: string | null;
  url: string;
}

export interface SearchResponse {
  query: string;
  results: {
    tickets: SearchResultItem[];
    problems: SearchResultItem[];
    kb: SearchResultItem[];
  };
  total_count: number;
}

/**
 * Perform a global search across tickets, problems, and KB articles.
 * Debounced on the caller side — do not call on every keystroke.
 *
 * @param query - Search query (min 2 chars)
 * @param types - Array of types to search: ["tickets", "problems", "kb"]
 * @param limit - Max results per type (default 5)
 * @returns SearchResponse with grouped results
 */
export async function globalSearch(
  query: string,
  types: string[] = ["tickets", "problems"],
  limit: number = 5
): Promise<SearchResponse> {
  const empty: SearchResponse = {
    query,
    results: { tickets: [], problems: [], kb: [] },
    total_count: 0,
  };
  try {
    if (!query || query.trim().length < 2) return empty;
    const params = new URLSearchParams({
      q: query.trim(),
      types: types.join(","),
      limit: String(limit),
    });
    const res = await fetch(`/api/search?${params.toString()}`);
    if (!res.ok) {
      console.warn("[globalSearch] API error", res.status);
      return empty;
    }
    return res.json();
  } catch {
    console.warn("[globalSearch] fetch failed");
    return empty;
  }
}
