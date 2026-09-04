/**
 * Programmatic SEO landing pages.
 *
 * Each entry becomes a statically generated route at `/tools/<slug>`, targeting
 * one high-intent query. These are the pages that earn organic traffic; the
 * playground itself is a client island and indexes for almost nothing.
 *
 * Rules for anything added here:
 *
 * 1. **One page per real intent.** A page that exists only to hold a keyword is
 *    thin content, and thin content at scale gets a site demoted rather than
 *    ranked.
 * 2. **Every factual claim has to be true.** These pages are about token
 *    accuracy; being caught with a wrong number here costs more than the
 *    traffic is worth. Do not put prices in this file — they live in the API's
 *    sourced pricing catalog and are rendered from it.
 * 3. **Answer the query above the fold**, then offer the tool. A page that
 *    withholds the answer to force a click loses the click.
 */

export interface ToolPage {
  slug: string;
  /** <title> — keep under ~60 chars so it is not truncated in results. */
  title: string;
  /** <meta description> — ~150-160 chars. */
  description: string;
  h1: string;
  /** The lede, which must directly answer the query. */
  answer: string;
  /** Body sections. Substance, not padding. */
  sections: { heading: string; body: string[] }[];
  faq: { q: string; a: string }[];
  /** Model ids to preselect when the visitor opens the playground. */
  presetModels: string[];
}

export const TOOL_PAGES: ToolPage[] = [
  {
    slug: "claude-token-counter",
    title: "Claude Token Counter — Exact Counts, No API Bill",
    description:
      "Count tokens for Claude Opus, Sonnet and Haiku exactly. Uses Anthropic's own token-counting endpoint, which costs nothing in tokens. No tiktoken guesswork.",
    h1: "Claude token counter",
    answer:
      "Paste your prompt and get an exact Claude token count. The count comes from Anthropic's own token-counting endpoint, so it is the same number they will bill you for — and calling it costs nothing in tokens.",
    sections: [
      {
        heading: "Why most Claude token counters are wrong",
        body: [
          "Almost every free \"Claude token counter\" runs tiktoken, which is OpenAI's tokenizer. It is not Anthropic's, and the two disagree: tiktoken undercounts Claude by roughly 15–20% on ordinary English prose, and by considerably more on code and non-English text.",
          "There is no public offline tokenizer for current Claude models. That means an accurate count requires a call to Anthropic's counting endpoint — which is free of token charges, but does require a key, which is why so many tools skip it and approximate instead.",
          "This one makes the call. When it cannot (rate limit, no key configured), it says so and labels the number as an estimate rather than quietly presenting a guess as fact.",
        ],
      },
      {
        heading: "Claude token counts are model-specific",
        body: [
          "The tokenizer changed within the Claude 4 generation. The same text can produce noticeably different counts on a 4.7-or-later model than on an earlier one, so a single \"Claude\" number is not meaningful — you have to count against the model you actually call.",
          "Pick the exact model in the tool and the count is measured against that model, not a family average.",
        ],
      },
      {
        heading: "Counting a request, not just text",
        body: [
          "Anthropic's endpoint counts a whole request, so its number includes the message framing you are billed for. A raw character-based or tiktoken-based count does not include that, which is another reason the two never match.",
          "Both numbers are shown, labelled, and never added together.",
        ],
      },
    ],
    faq: [
      {
        q: "Does counting Claude tokens cost money?",
        a: "No. Anthropic's token-counting endpoint does not charge for the tokens it counts. It is rate-limited and requires an API key, but it does not consume your token budget.",
      },
      {
        q: "Can I count Claude tokens offline?",
        a: "Not accurately. Anthropic does not publish an offline tokenizer for current Claude models, so any offline figure is an approximation. This tool shows an approximation only while the exact count loads, and marks it with a ≈ symbol.",
      },
      {
        q: "Why is the Claude count higher than the GPT-4o count for the same text?",
        a: "Different tokenizers segment text differently, and Anthropic's count includes request framing. Neither number is wrong; they measure different things and are not interchangeable.",
      },
    ],
    presetModels: ["claude-opus-5", "gpt-4o"],
  },
  {
    slug: "reduce-openai-api-bill",
    title: "How to Reduce Your OpenAI API Bill (Measured, Not Guessed)",
    description:
      "Cut input tokens with lossless prompt cleanup, JSON-to-table conversion and prompt caching. See exactly what each change saves before you ship it.",
    h1: "How to reduce your OpenAI API bill",
    answer:
      "The largest wins are almost never clever prompt rewriting. They are: converting repeated-key JSON into tables, caching stable prefixes, and stripping formatting whitespace — in that order. Paste a real prompt below and each change is measured by re-tokenizing, not estimated.",
    sections: [
      {
        heading: "1. Convert JSON payloads to tables",
        body: [
          "An array of uniform objects repeats every key on every row. A Markdown table states each key once. On data-heavy prompts this is typically the single biggest reduction available, and it is by far the most under-used.",
          "It is not free of consequence: cell values lose their JSON types, so review it if your prompt depends on strict typing. The tool applies it, shows the diff, and lets you turn it off.",
        ],
      },
      {
        heading: "2. Cache your stable prefix instead of compressing it",
        body: [
          "If a large system prompt goes out unchanged on every call, prompt caching will save far more than compressing it — cached input is billed at a fraction of the base rate.",
          "There is a trap here worth knowing: editing a cached prefix invalidates the cache. Compressing a stable system prompt can therefore cost you more on the next call than it saves. Compress the volatile tail; cache the stable head.",
        ],
      },
      {
        heading: "3. Strip whitespace and normalise Unicode",
        body: [
          "Curly quotes, em dashes, non-breaking spaces and CRLF line endings all cost more tokens than their ASCII equivalents while meaning exactly the same thing. Anything pasted out of a word processor, a wiki, or a chat client is usually full of them.",
          "Individually tiny; collectively worth a few percent on real prompts, at zero risk.",
        ],
      },
      {
        heading: "What will not save you money",
        body: [
          "Compressing your prompt does not shorten the model's response. Input and output are billed separately, so prompt optimization reduces the input side only. Any calculator showing a shrinking \"total cost\" while holding output constant is taking credit for something it did not do.",
          "Deleting politeness is also oversold. It does save a few tokens, and it can also cost you tokens: removing \"Please \" forces \"summarize\" to become \"Summarize\", which tokenizes worse. This tool measures each change and refuses any that would make things worse.",
        ],
      },
    ],
    faq: [
      {
        q: "Does shortening my prompt reduce output cost too?",
        a: "No. Output length is set by what the model decides to write, not by how long your prompt was. Prompt optimization reduces input cost only.",
      },
      {
        q: "How much can I realistically save?",
        a: "It depends entirely on what your prompt contains. Pretty-printed JSON payloads can drop by a third or more. An already-tight prompt may save almost nothing — and the tool will tell you that rather than manufacture a number.",
      },
      {
        q: "Is shorter text always fewer tokens?",
        a: "No, and this is the most common misconception. Tokenizers merge common character sequences, so removing a character can split a token that was previously whole. Savings have to be measured by re-tokenizing, which is what this tool does.",
      },
    ],
    presetModels: ["gpt-4o", "claude-opus-5"],
  },
  {
    slug: "gpt-4o-token-counter",
    title: "GPT-4o Token Counter — Offline, Exact, With Token Map",
    description:
      "Count GPT-4o tokens exactly in your browser with the o200k_base tokenizer. See where every token boundary falls. Your text is never uploaded.",
    h1: "GPT-4o token counter",
    answer:
      "Exact GPT-4o token counts, computed in your browser with the model's own o200k_base tokenizer. Your text is never uploaded for this — and you can see precisely where each token boundary falls.",
    sections: [
      {
        heading: "Why this one runs in your browser",
        body: [
          "OpenAI's tokenizer is published, so it can run locally. That means an exact count with no network round trip, no API key, no rate limit, and no prompt leaving your machine. For GPT-4o and the rest of the OpenAI family, there is no reason to upload anything.",
          "Turn on Local-only mode and the page makes no server requests at all.",
        ],
      },
      {
        heading: "The token map",
        body: [
          "Because the OpenAI tokenizer reverses cleanly to bytes, exact per-token character boundaries can be reconstructed. The editor shades alternating tokens so you can see which parts of your prompt are expensive.",
          "This is available for the OpenAI family only. Anthropic's and Google's counting endpoints return a total with no segmentation, so there is no honest way to draw their boundaries — and we do not fake it by relabelling OpenAI's.",
        ],
      },
      {
        heading: "Raw text tokens vs billed request tokens",
        body: [
          "A tokenizer counts the characters you give it. A chat completion also bills per-message framing overhead, and tool or function definitions on top. The raw count is the right number for comparing two versions of a prompt; the billed count is the right number for a cost estimate.",
          "They are shown as separate figures, because conflating them is how cost estimates end up wrong.",
        ],
      },
    ],
    faq: [
      {
        q: "Which encoding does GPT-4o use?",
        a: "o200k_base. GPT-4 and GPT-3.5-turbo use the older cl100k_base, which is why the same text yields different counts across those models. The tool selects the encoding from the model you pick.",
      },
      {
        q: "Is my prompt uploaded?",
        a: "Not for OpenAI counts — those run entirely in your browser in a Web Worker. Claude and Gemini counts do require a server call, because neither has a public offline tokenizer. Local-only mode disables all server calls.",
      },
    ],
    presetModels: ["gpt-4o", "gpt-4o-mini"],
  },
  {
    slug: "json-prompt-compressor",
    title: "JSON Prompt Compressor — Cut Repeated Keys From Prompts",
    description:
      "Turn pretty-printed JSON in your prompts into token-light Markdown tables. Verified lossless where it can be, with the diff shown before you copy.",
    h1: "JSON prompt compressor",
    answer:
      "Pretty-printed JSON is the most expensive thing most people paste into a prompt. Compacting it is verified lossless; converting a uniform array into a table removes every repeated key and is usually the single largest saving available.",
    sections: [
      {
        heading: "Two separate transforms",
        body: [
          "Compacting JSON strips formatting whitespace only. It is checked by re-parsing both versions and comparing them, so it is emitted only when provably information-preserving. This runs at every optimization level.",
          "Converting an array of uniform objects into a Markdown table goes further: it removes the repeated keys entirely. This is where the large savings are, and it is a representation change rather than a pure cleanup — so it is applied at Balanced and above, with the diff shown.",
        ],
      },
      {
        heading: "When the table conversion is refused",
        body: [
          "It only fires on arrays of flat objects that all share the same keys. Ragged records, nested objects, and duplicate keys are all skipped, because tabling them would silently drop data — and a compressor that loses fields is worse than no compressor.",
          "Values also lose their JSON types in a table: 3 and \"3\" both render as 3. If your prompt depends on strict typing, leave this rule off.",
        ],
      },
      {
        heading: "Your code is not touched",
        body: [
          "Before any rule runs, the text is classified into protected regions: fenced code blocks, inline code, URLs, template variables, email addresses, and base64 blobs. No cleanup rule is allowed to modify any of them.",
          "This matters more than it sounds. Collapsing whitespace inside a Python block or a JSON string literal is a data-destroying bug, and it is the most common failure in naive prompt compressors.",
        ],
      },
    ],
    faq: [
      {
        q: "Is JSON compaction lossless?",
        a: "Yes, and it is verified rather than assumed: both versions are parsed and compared before the change is emitted. Input with duplicate keys is skipped, because a round trip through a parser would silently collapse them.",
      },
      {
        q: "Should I send the model a table instead of JSON?",
        a: "Usually yes for tabular data, but test it. If your prompt asks the model to return valid JSON, or depends on the input's types, the table form can change behaviour. That is why it is shown as a diff you approve rather than applied silently.",
      },
      {
        q: "What about base64 images in my prompt?",
        a: "Base64 tokenizes terribly and no compression fixes it. The tool flags it and tells you to use the provider's file or vision API instead of pasting it as text — which is advice, not a transform.",
      },
    ],
    presetModels: ["gpt-4o", "claude-opus-5"],
  },
];

export function getToolPage(slug: string): ToolPage | undefined {
  return TOOL_PAGES.find((page) => page.slug === slug);
}
