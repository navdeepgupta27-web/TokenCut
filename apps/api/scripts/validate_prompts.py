"""Run the validation prompts through the live API and print a report.

Every number in the delivered examples comes from this script, not from
estimation.
"""

import json
import urllib.request

API = "http://127.0.0.1:8000/v1/analyze"
MODELS = ["gpt-4o", "claude-opus-5"]


def analyze(text, models=None, profile="balanced", tokens_out=400, calls=30000, overrides=None):
    body = {
        "text": text,
        "models": models or MODELS,
        "profile": profile,
        "rules": overrides or {},
        "include_offsets": False,
        "include_segments": False,
        "tokens_out": tokens_out,
        "calls_per_month": calls,
        "cache_read_fraction": 0,
        "cache_write_fraction": 0,
        "batch_fraction": 0,
    }
    req = urllib.request.Request(
        API, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


CASES = []


def case(name, kind, text, **kw):
    CASES.append((name, kind, text, kw))


# ---------------------------------------------------------------- SHORT ----

case(
    "S1 · Politeness that costs more to remove",
    "short",
    "Please summarize this document carefully.",
    overrides={"flag_politeness": True},
)

case(
    "S2 · Smart quotes and em dashes from a word processor",
    "short",
    "The report said “operational efficiency” improved — by 14% — "
    "year‑over‑year… driven by automation.",
)

case(
    "S3 · Tiny JSON, table conversion correctly declined",
    "short",
    'Rank these: [{"id":1,"n":"Ada"},{"id":2,"n":"Grace"}]',
)

case(
    "S4 · Duplicated constraint and hedge stacking",
    "short",
    "Answer very carefully and thoroughly and precisely.\n"
    "Do not use markdown.\n"
    "Do not use markdown.",
)

case(
    "S5 · Base64 blob — advice, not compression",
    "short",
    "Describe this image: " + "A" * 320,
)

case(
    "S6 · Already-tight prompt (honest zero)",
    "short",
    "Classify the sentiment of the review below as positive, negative or neutral.",
)

# ----------------------------------------------------------------- LONG ----

RECORDS = [
    {"id": i, "name": f"Customer {i}", "plan": ["starter", "pro", "enterprise"][i % 3],
     "mrr": 49 + i * 137, "seats": 2 + i * 3, "last_login_days": (i * 7) % 90,
     "region": ["emea", "amer", "apac"][i % 3]}
    for i in range(1, 41)
]

case(
    "L1 · Bloated JSON payload (40 records, pretty-printed)",
    "long",
    "You are a revenue analyst. Analyse the customer records below and identify "
    "churn risk.\n\nRecords:\n" + json.dumps(RECORDS, indent=2) +
    "\n\nReturn the five highest-risk accounts with a one-line reason each.",
)

case(
    "L2 · Verbose system prompt with every audit smell",
    "long",
    """You are a helpful assistant. You are a world-class customer support agent.

Please, if you could, take a deep breath and read the customer's message very
carefully and thoroughly and precisely before you respond.

It is very important that you always remember to be polite and courteous. I
would like you to answer in a friendly tone. Thank you very much for your help!

As an AI language model, you should be aware of the following constraints:

Do not use markdown formatting.
Never include markdown formatting in your reply.
Do not mention that you are an AI.
Do not mention that you are an AI.

You are a helpful and courteous support agent who always helps the customer.

In this task, you will read the customer's question and answer it using only
the knowledge base provided below. Remember that you must not invent facts.

Now answer the customer's question below.""",
)

case(
    "L3 · RAG context with whitespace rot and a repeated preamble",
    "long",
    """### Retrieved context

You are answering strictly from the context below. Do not use outside knowledge.

---

Document 1:
The   quarterly   report   noted   that  “operational  efficiency”  improved  by
14%   year-over-year   —   driven   primarily   by   automation   of   the
reconciliation   pipeline…



Document 2:
You are answering strictly from the context below. Do not use outside knowledge.

The   same   report   observed   that   headcount   remained   flat   while
transaction   volume   grew   by   28%,   which   management   described   as
“durable  leverage”  in  the  cost  base…



Document 3:
Margins    expanded    by    310    basis    points,    although    the
report    cautioned    that    the    comparison    period    included    a
one‑off    restructuring    charge…


Question: what drove the efficiency gain?""",
)

case(
    "L4 · Mixed content — code fences must survive aggressive mode",
    "long",
    """Please review  the  function  below  and  suggest  improvements.

```python
def reconcile(ledger: dict, txns: list) -> Report:
    total  =  sum(t.amount  for  t  in  txns  if  not  t.voided)
    s = '  three   spaces  preserved  '
    if total != ledger['expected']:
        raise ReconciliationError(total, ledger['expected'])
    return Report(total=total, count=len(txns))
```

Config used:
{
    "tolerance":     0.01,
    "currency":      "USD",
    "strict_mode":   true
}

Call the endpoint at https://api.example.com/v1/reconcile?strict=true  and
greet  {{user_name}}  using  ${greeting}  in  your  reply.

Thank you very much!""",
    profile="aggressive",
)

case(
    "L5 · Large stable system prefix — caching should be advised",
    "long",
    "You are an expert legal assistant.\n\n" + (
        "When reviewing a contract clause, consider the governing law, the "
        "limitation of liability, the indemnity scope, and the termination "
        "triggers. Flag any deviation from our standard playbook. "
    ) * 60 + "\n\nNow review the clause pasted below.",
)


def run():
    print("=" * 78)
    for kind_filter in ("short", "long"):
        print(f"\n{'#' * 78}\n#  {kind_filter.upper()} PROMPTS\n{'#' * 78}")
        for name, kind, text, kw in CASES:
            if kind != kind_filter:
                continue
            d = analyze(text, **kw)
            o = d["optimize"]
            tk = {r["model"]: r for r in d["tokenize"]["results"]}
            tka = {r["model"]: r for r in d["tokenize_optimized"]["results"]}
            cost = {r["model"]: r for r in d["cost"]["results"]}

            before = o["tokens_before"]
            after = o["tokens_after"]
            pct = (before - after) / before * 100 if before else 0.0

            print(f"\n{name}")
            print(f"  chars {len(text):>6}   profile {kw.get('profile', 'balanced')}")
            print(f"  gpt-4o        {tk['gpt-4o']['tokens']:>6} -> {tka['gpt-4o']['tokens']:<6} "
                  f"({tk['gpt-4o']['source']})")
            c = tk["claude-opus-5"]
            ca = tka["claude-opus-5"]
            print(f"  claude-opus-5 {c['tokens']:>6} -> {ca['tokens']:<6} ({c['source']}"
                  f"{', calibrated=' + str(c['calibrated']) if c['source'] == 'estimated' else ''})")
            print(f"  reduction     {pct:>5.1f}%")

            g = cost.get("gpt-4o", {})
            k = cost.get("claude-opus-5", {})
            if g.get("available"):
                print(f"  saved/mo      gpt-4o ${g['saved_per_month']:.2f}   "
                      f"claude-opus-5 ${k['saved_per_month']:.2f}  (@30k calls)")

            if o["applied"]:
                print("  applied:")
                for a in o["applied"]:
                    print(f"    - {a['rule_id']:<26} -{a['tokens_saved']:<4} x{a['occurrences']}")
            else:
                print("  applied:   (nothing — already tight)")

            if o["suggested"]:
                print("  suggested (not applied):")
                for s in o["suggested"]:
                    amt = "advice" if s["category"] == "advisory" else f"-{s['tokens_saved_if_applied']}"
                    print(f"    - {s['rule_id']:<26} {amt:<7} x{s['occurrences']}")

            for w in o["warnings"]:
                if "would ADD" in w or "skipped" in w:
                    print(f"  ! {w}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    run()
