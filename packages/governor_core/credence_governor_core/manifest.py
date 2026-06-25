"""manifest.py — parse capabilities.bdsl and features.bdsl from data/bdsl/, verify
the daemon has implementations/extractors for every declared effector and feature.
Body-side; the brain runs the full BDSL evaluator. Pass-1 manifests use only
symbols and parens. Port of credence-openclaw extension/src/manifest.ts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union

SExpr = Union[str, list["SExpr"]]


@dataclass
class EffectorParam:
    name: str
    type: str


@dataclass
class EffectorDecl:
    name: str
    parameters: list[EffectorParam] = field(default_factory=list)


@dataclass
class FeatureDecl:
    name: str
    space_name: str


def _tokenize(src: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c == ";":
            while i < n and src[i] != "\n":
                i += 1
        elif c in " \t\n\r":
            i += 1
        elif c in "()":
            tokens.append(c)
            i += 1
        else:
            j = i
            while j < n and src[j] not in " \t\n\r();":
                j += 1
            tokens.append(src[i:j])
            i = j
    return tokens


def _read(tokens: list[str]) -> list[SExpr]:
    pos = 0

    def read_one() -> SExpr:
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError("manifest: unexpected end of input")
        tok = tokens[pos]
        pos += 1
        if tok == "(":
            lst: list[SExpr] = []
            while pos < len(tokens) and tokens[pos] != ")":
                lst.append(read_one())
            if pos >= len(tokens):
                raise ValueError("manifest: missing closing ')'")
            pos += 1
            return lst
        if tok == ")":
            raise ValueError("manifest: unexpected ')'")
        return tok

    out: list[SExpr] = []
    while pos < len(tokens):
        out.append(read_one())
    return out


def _fmt(e: SExpr | None) -> str:
    if e is None:
        return "<undefined>"
    if isinstance(e, list):
        return "(" + " ".join(_fmt(x) for x in e) + ")"
    return e


def _collect(exprs: list[SExpr], head: str, parse_one) -> list:
    out: list = []

    def visit(e: SExpr) -> None:
        if not isinstance(e, list):
            return
        if len(e) > 0 and e[0] == head:
            out.append(parse_one(e))
            return
        for child in e:
            visit(child)

    for e in exprs:
        visit(e)
    return out


def _parse_effector_form(form: list[SExpr]) -> EffectorDecl:
    if len(form) < 2 or not isinstance(form[1], str):
        raise ValueError(f"manifest: effector form missing name in {_fmt(form)}")
    name = form[1]
    parameters: list[EffectorParam] = []
    for i in range(2, len(form)):
        clause = form[i]
        if not isinstance(clause, list) or not clause or clause[0] != "parameters":
            raise ValueError(f"manifest: effector {name}: expected (parameters ...), got {_fmt(clause)}")
        for j in range(1, len(clause)):
            p = clause[j]
            if not isinstance(p, list) or len(p) != 2 or not isinstance(p[0], str) or not isinstance(p[1], str):
                raise ValueError(f"manifest: effector {name}: parameter must be (name type), got {_fmt(p)}")
            parameters.append(EffectorParam(name=p[0], type=p[1]))
    return EffectorDecl(name=name, parameters=parameters)


def _parse_feature_form(form: list[SExpr]) -> FeatureDecl:
    if len(form) != 3 or not isinstance(form[1], str) or not isinstance(form[2], str):
        raise ValueError(f"manifest: feature form must be (feature NAME SPACE), got {_fmt(form)}")
    return FeatureDecl(name=form[1], space_name=form[2])


def parse_sexprs(src: str) -> list[SExpr]:
    return _read(_tokenize(src))


def parse_capabilities(src: str) -> list[EffectorDecl]:
    return _collect(_read(_tokenize(src)), "effector", _parse_effector_form)


def parse_features(src: str) -> list[FeatureDecl]:
    exprs = _read(_tokenize(src))
    # Scope to the `(define features (list ...))` form — the features THIS body emits and
    # must have extractors for. A separate `(define safety-features ...)` declares the harm
    # posterior's vocabulary, validated separately.
    features_form: list[SExpr] | None = None
    for e in exprs:
        if isinstance(e, list) and len(e) >= 2 and e[0] == "define" and e[1] == "features":
            features_form = e
            break
    scope = [features_form] if features_form is not None else exprs
    return _collect(scope, "feature", _parse_feature_form)


def read_capabilities(path: str) -> list[EffectorDecl]:
    with open(path, encoding="utf-8") as f:
        return parse_capabilities(f.read())


def read_features(path: str) -> list[FeatureDecl]:
    with open(path, encoding="utf-8") as f:
        return parse_features(f.read())


def verify_effectors(decls: list[EffectorDecl], registry: dict) -> None:
    missing = [d.name for d in decls if d.name not in registry]
    if missing:
        raise ValueError(
            f"manifest: no implementation registered for declared effector(s): {', '.join(missing)}"
        )


def verify_features(decls: list[FeatureDecl], registry: dict) -> None:
    missing = [d.name for d in decls if d.name not in registry]
    if missing:
        raise ValueError(
            f"manifest: no extractor registered for declared feature(s): {', '.join(missing)}"
        )
