import re

_KNOWN_COMMANDS = sorted([
    "mathbb", "mathrm", "mathbf", "mathit", "mathcal",
    "times", "cdot", "sqrt", "frac", "sum", "prod", "int",
    "sin", "cos", "tan", "log", "exp", "argmax", "argmin",
    "top", "dots", "ldots", "cdots", "vdots", "partial", "nabla",
    "notin", "subseteq", "supseteq", "subset", "cup", "cap",
    "forall", "exists", "infty", "approx", "equiv", "neq", "leq", "geq",
    "rightarrow", "leftarrow", "Rightarrow", "Leftarrow",
    "left", "right", "Bigl", "Bigr", "bigl", "bigr", "Big", "big",
    "alpha", "beta", "gamma", "delta", "epsilon", "theta", "lambda",
    "mu", "sigma", "phi", "omega", "pi", "Sigma", "Delta", "Omega",
    "text", "softmax", "concat", "in", "max", "min", "to",
], key=len, reverse=True)

_COMMAND_RE = re.compile("(" + "|".join(_KNOWN_COMMANDS) + ")")
_MATH_SPAN_RE = re.compile(r"(\${1,2})(.+?)\1", re.DOTALL)


def _repair_math_span(inner: str) -> str:
    """Longest-match tokenizer pass: walk the string, and wherever a known
    command name appears NOT already preceded by a backslash, reinsert one.
    Text already correctly backslash-escaped is left untouched (the escaped
    command is skipped over as a unit so we never double-escape it)."""
    out = []
    i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "\\":
            m = _COMMAND_RE.match(inner, i + 1)
            if m:
                out.append(inner[i : i + 1 + len(m.group(1))])
                i += 1 + len(m.group(1))
                continue
            out.append(ch)
            i += 1
            continue

        m = _COMMAND_RE.match(inner, i)
        if m:
            out.append("\\" + m.group(1))
            i += len(m.group(1))
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def repair_latex(text: str) -> str:
    """Scan $...$/$$...$$ spans in `text` and reinsert missing backslashes
    on recognized glued LaTeX commands. Text outside math spans (ordinary
    prose) is returned completely unchanged — this is what makes the
    function safe to run unconditionally on any final_answer string."""
    def span_repl(m):
        delim, inner = m.group(1), m.group(2)
        return delim + _repair_math_span(inner) + delim

    return _MATH_SPAN_RE.sub(span_repl, text)