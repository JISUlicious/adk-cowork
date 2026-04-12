---
name: research
description: "Use when the user wants to research a topic by searching the web and summarizing sources."
license: MIT
---

# research

Conduct a short research loop using `search_web` and `http_fetch`.

## Workflow

1. **Search**: call `search_web(query)` to get a list of results with titles, URLs, and snippets.
2. **Evaluate**: pick the 2-4 most relevant results based on title and snippet.
3. **Fetch**: call `http_fetch(url)` on each to get the full page content.
4. **Summarize**: extract key facts and write a summary with source citations.
5. **Save**: write the summary to `scratch/research.md` using `fs_write`.

## Example flow

```
1. search_web("quarterly earnings report format best practices", max_results=5)
2. Review snippets, pick top 3 URLs
3. http_fetch("https://example.com/article1") for each
4. Synthesize into a concise summary
5. fs_write("scratch/research.md", summary_text)
```

## Output format

Write research results as Markdown with:
- A one-paragraph summary at the top
- Key findings as bullet points
- A "Sources" section at the bottom listing each URL with a one-line description

## Notes

- No API keys needed — `search_web` uses DuckDuckGo by default.
- `http_fetch` returns text content; it won't render JavaScript.
- Keep fetches to 2-4 pages to stay responsive.
- Always cite sources — never present fetched content as original.
