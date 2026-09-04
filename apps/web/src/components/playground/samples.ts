/**
 * Empty-state samples.
 *
 * Each is chosen because it produces a visibly large, *honest* saving — the
 * first one demonstrates the JSON-to-table rule, which is the engine's biggest
 * real lever. A demo that only saves 2% teaches the visitor that the tool does
 * not work.
 */

export interface Sample {
  id: string;
  label: string;
  blurb: string;
  text: string;
}

export const SAMPLES: Sample[] = [
  {
    id: "json-payload",
    label: "Bloated JSON payload",
    blurb: "Pretty-printed records — the biggest single win",
    text: `You are a revenue analyst. Analyse the following customer records and identify churn risk.

Records:
[
  {
    "id": 1,
    "name": "Ada Lovelace",
    "plan": "enterprise",
    "mrr": 1200,
    "seats": 40,
    "last_login_days": 2
  },
  {
    "id": 2,
    "name": "Grace Hopper",
    "plan": "pro",
    "mrr": 300,
    "seats": 8,
    "last_login_days": 31
  },
  {
    "id": 3,
    "name": "Katherine Johnson",
    "plan": "enterprise",
    "mrr": 1500,
    "seats": 55,
    "last_login_days": 1
  },
  {
    "id": 4,
    "name": "Radia Perlman",
    "plan": "starter",
    "mrr": 49,
    "seats": 2,
    "last_login_days": 74
  }
]

Return the three highest-risk accounts with a one-line reason each.`,
  },
  {
    id: "verbose-system",
    label: "Verbose system prompt",
    blurb: "Politeness, filler and duplicated constraints",
    text: `You are a helpful assistant. You are a world-class customer support agent.

Please, if you could, take a deep breath and read the customer's message very carefully and thoroughly and precisely before you respond.

It is very important that you always remember to be polite. I would like you to answer in a friendly tone. Thank you very much for your help!

Do not use markdown formatting.
Never include markdown formatting in your reply.

You are a helpful and courteous support agent who always helps.

Now answer the customer's question below.`,
  },
  {
    id: "rag-context",
    label: "RAG context block",
    blurb: "Whitespace, smart quotes and a repeated preamble",
    text: `### Retrieved context

You are answering strictly from the context below.

---

Document 1:
The   quarterly   report   noted   that  “operational  efficiency”  improved  by
14%   year-over-year   —   driven   primarily   by   automation   of   the
reconciliation   pipeline…



Document 2:
You are answering strictly from the context below.

The   same   report   observed   that   headcount   remained   flat   while
transaction   volume   grew   by   28%,   which   management   described   as
“durable  leverage”  in  the  cost  base…



Question: what drove the efficiency gain?`,
  },
];
