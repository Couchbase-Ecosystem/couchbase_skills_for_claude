# Search Service analyzers

- [Built-in analyzers](#built-in-analyzers)
- [Custom analyzers](#custom-analyzers)
- [Character filters](#character-filters)
- [Tokenizers](#tokenizers)
- [Token filters](#token-filters)
- [Choosing an analyzer](#choosing-an-analyzer-for-common-use-cases)
- [Analyzer consistency rule](#analyzer-consistency-rule)

An analyzer is a pipeline: character filters → tokenizer → token filters. The same analyzer runs at index time and query time. Mismatch = missed matches.

## Built-in analyzers

| Analyzer name | Tokenizer | Token filters | When to use |
|---|---|---|---|
| `standard` | Unicode word boundary | Lowercase | General English text; no stemming |
| `en` | Unicode | Lowercase, stop words (English), English stemmer | English content where "runs" should match "run" |
| `keyword` | Single token (whole value) | Lowercase | Short exact strings — use `keyword` field *type* instead when possible |
| `simple` | Letter characters only | Lowercase | Simple text without stop-word or stemming needs |
| `web` | Unicode | Lowercase | Web content; strips common stop words |
| `de` | Unicode | Lowercase, German stop words, German stemmer | German text |
| `fr` | Unicode | Lowercase, French stop words, French stemmer | French text |
| `es` | Unicode | Lowercase, Spanish stop words, Spanish stemmer | Spanish text |
| `it` | Unicode | Lowercase, Italian stop words, Italian stemmer | Italian text |
| `pt` | Unicode | Lowercase, Portuguese stop words, Portuguese stemmer | Portuguese text |
| `ar` | Unicode | Arabic normalization, lowercase, Arabic stop words | Arabic text |
| `cjk` | Unicode bigram | Lowercase | Chinese, Japanese, Korean |
| `detect_lang` | — | Language detector + routes to language analyzer | Multi-language collections |



## Custom analyzers

When built-ins don't fit, define a custom analyzer in the index definition under `analysis.analyzers`:

```json
"analysis": {
  "char_filters": {
    "strip_html": { "type": "html" }
  },
  "tokenizers": {
    "word_break": { "type": "unicode" }
  },
  "token_filters": {
    "edge_ngram": {
      "type": "edge_ngram",
      "min": 2,
      "max": 10,
      "back": false
    },
    "lower": { "type": "to_lower" }
  },
  "analyzers": {
    "autocomplete_analyzer": {
      "type": "custom",
      "char_filters": ["strip_html"],
      "tokenizer": "word_break",
      "token_filters": ["lower", "edge_ngram"]
    }
  }
}
```

Then reference it in a field mapping: `"analyzer": "autocomplete_analyzer"`.

## Character filters

| Type | What it does |
|---|---|
| `html` | Strips HTML tags |
| `mapping` | Replaces character sequences via a mapping table |
| `regexp` | Replaces regexp matches |
| `zero_width_non_joiner` | Strips zero-width non-joiners (Arabic/Persian text prep) |

## Tokenizers

| Type | What it does |
|---|---|
| `unicode` | Splits on Unicode word boundaries (recommended for most languages) |
| `letter` | Splits on letter sequences (ignores numbers and punctuation) |
| `whitespace` | Splits on whitespace only |
| `single` | Whole value as one token (for keyword-style fields) |
| `exception` | Composite: exception list + fallback tokenizer |
| `regexp` | Splits on a regular expression |

## Token filters

| Type | What it does |
|---|---|
| `to_lower` | Lowercases all tokens |
| `stop_tokens` | Removes stop words (a, the, is, etc.) — specify a list or use a built-in set |
| `stemmer_en_snowball` | English Snowball stemmer |
| `stemmer_de_light` | German light stemmer |
| `edge_ngram` | Generates n-grams from the start of each token (autocomplete) |
| `ngram` | Generates n-grams from anywhere in the token |
| `truncate_token` | Truncates tokens to max length |
| `normalize_unicode` | Unicode NFC/NFD normalization |
| `cld2` | Language detection |

## Choosing an analyzer for common use cases

**English content, relevance ranking.** Use `en`. Handles stemming and stop words. Documents about "running" and "run" will match "run" queries.

**Exact-match status / tag / enum fields.** Use the `keyword` field type, not a text field with keyword analyzer. The type difference matters for how the field is stored and queried.

**Autocomplete / type-ahead.** Build a custom analyzer with `edge_ngram` token filter. Index with it; query with `standard` or `en` (don't apply edge_ngram at query time — it generates nonsense query terms).

**Multi-language content.** Option 1: `detect_lang` analyzer (auto-routes to language analyzer). Option 2: separate fields per language (`title_en`, `title_de`) with their respective analyzers. Option 3: `standard` as the lowest common denominator (no language-specific stemming).

**SKUs / product codes / IDs.** Use `keyword` field type for exact match. If you need prefix search on them (e.g. `SKU-1*`), use a text field with a custom analyzer that uses the `whitespace` or `letter` tokenizer without stemming.

**HTML body content.** Custom analyzer with `html` char filter + `unicode` tokenizer + `en` token filters.

## Analyzer consistency rule

The analyzer used at query time must match the analyzer used at index time for `match` and `match_phrase` queries. For `term`, `terms`, `prefix`, `wildcard`, and `regexp` queries, no analyzer is applied — you're matching against the raw indexed token. If your indexed terms are lowercased (they usually are), lowercase your term/prefix/wildcard query values manually.

Example: field indexed with `en` analyzer, which lowercases and stems. A `term` query for `"Running"` will miss; `"run"` (stemmed, lowercase) will hit. A `match` query for `"Running"` will work because the Search Service applies the `en` analyzer to the query string, producing `"run"`.

**Synonyms (8.0+) are analyzer-coupled too.** A synonym source declares an analyzer, and a field only uses that source if the analyzers match. Changing a field's analyzer can silently switch off synonym expansion on it.
