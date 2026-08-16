import re

_KNOWN_COMMANDS = [
    "mathbb",
    "mathrm",
    "mathbf",
    "mathit",
    "mathcal",
    "times",
    "cdot",
    "sqrt",
    "frac",
    "sum",
    "prod",
    "int",
    "sin",
    "cos",
    "tan",
    "log",
    "exp",
    "argmax",
    "argmin",
    "top",
    "dots",
    "ldots",
    "cdots",
    "vdots",
    "partial",
    "nabla",
    "notin",
    "subseteq",
    "supseteq",
    "subset",
    "cup",
    "cap",
    "forall",
    "exists",
    "infty",
    "approx",
    "equiv",
    "neq",
    "leq",
    "geq",
    "rightarrow",
    "leftarrow",
    "Rightarrow",
    "Leftarrow",
    "left",
    "right",
    "Bigl",
    "Bigr",
    "bigl",
    "bigr",
    "Big",
    "big",
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "theta",
    "lambda",
    "mu",
    "sigma",
    "phi",
    "omega",
    "pi",
    "Sigma",
    "Delta",
    "Omega",
    "text",
    "softmax",
    "concat",
    "in",
    "max",
    "min",
    "to",
]

_KNOWN_COMMANDS = sorted(_KNOWN_COMMANDS, key=len, reverse=True)

_CMD_ALT = "|".join(re.escape(cmd) for cmd in _KNOWN_COMMANDS)

_COMMAND_RE = re.compile(
    r"(?<![A-Za-z0-9_\\])(" + _CMD_ALT + r")(?![A-Za-z0-9_])"
)

_COMMAND_NO_LB_RE = re.compile(
    r"(" + _CMD_ALT + r")(?![A-Za-z0-9_])"
)

_DOUBLE_ESCAPED_CMD_RE = re.compile(
    r"\\\\(?P<name>" + _CMD_ALT + r")(?![A-Za-z0-9_])"
)

_NON_MACRO_FUNCTIONS = frozenset({"softmax", "concat"})

_MATH_SPAN_RE = re.compile(
    r"(\${1,2})([^$]+?)\1",
    re.DOTALL,
)


def _repair_math_span(inner: str) -> str:
    """
    Walk the math span and repair backslash usage around known command tokens.

    Rules:
    - If a backslash already exists, do not double-escape.
    - Collapse double-escaped known commands (``\\sqrt`` -> ``\\sqrt``).
    - Never invent a backslash for non-macro function names
      (``softmax(...)`` stays ``softmax(...)``; ``\\softmax`` -> ``softmax``).
    - Only repair known command tokens.
    - Leave normal prose inside math unchanged except for known tokens.
    """
    out = []
    i = 0
    n = len(inner)

    while i < n:
        ch = inner[i]

        if ch == "\\":
            m = _COMMAND_NO_LB_RE.match(inner, i + 1)
            if m:
                name = m.group(1)
                if name in _NON_MACRO_FUNCTIONS:
                    out.append(name)
                else:
                    out.append("\\" + name)
                i += 1 + len(name)
                continue

            m2 = _DOUBLE_ESCAPED_CMD_RE.match(inner, i)
            if m2:
                name = m2.group("name")
                if name in _NON_MACRO_FUNCTIONS:
                    out.append(name)
                else:
                    out.append("\\" + name)
                i += 2 + len(name)
                continue

            out.append(ch)
            i += 1
            continue

        m = _COMMAND_RE.match(inner, i)
        if m:
            name = m.group(1)
            if name in _NON_MACRO_FUNCTIONS:
                out.append(name)
            else:
                out.append("\\" + name)
            i += len(name)
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def repair_latex(text: str) -> str:
    """
    Scan $...$ / $$...$$ spans and repair missing LaTeX backslashes.

    Text outside math spans is left unchanged.
    """
    if not text:
        return text

    def span_repl(m):
        delim = m.group(1)
        inner = m.group(2)
        repaired = _repair_math_span(inner)
        return f"{delim}{repaired}{delim}"

    return _MATH_SPAN_RE.sub(span_repl, text)