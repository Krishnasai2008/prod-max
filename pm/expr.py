"""A small arithmetic evaluator for template formulas: an ast walk over a whitelist, never eval."""
import ast
import math
import operator

MAX_LEN = 300
MAX_SIZE = 1e15


def _factorial(n):
    if n != int(n) or n < 0:
        raise ValueError("factorial needs a whole number 0 or more")
    if n > 20:
        raise ValueError("that number is too large")
    return math.factorial(int(n))


def _comb(n, k):
    if n != int(n) or k != int(k) or n < 0 or k < 0:
        raise ValueError("comb needs whole numbers 0 or more")
    if n > 60 or k > 60:
        raise ValueError("that number is too large")
    return math.comb(int(n), int(k))


def _int_args(f):
    def call(*args):
        if any(a != int(a) for a in args):
            raise ValueError(f"{f.__name__} needs whole numbers")
        return f(*(int(a) for a in args))
    return call


FUNCTIONS = {"min": min, "max": max, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
             "sqrt": math.sqrt, "gcd": _int_args(math.gcd), "comb": _comb, "factorial": _factorial,
             "log": math.log, "exp": math.exp}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt, ast.LtE: operator.le,
            ast.Gt: operator.gt, ast.GtE: operator.ge}
_WHAT = {ast.Attribute: "attribute access", ast.Subscript: "a subscript", ast.Lambda: "a lambda",
         ast.List: "a list", ast.Tuple: "a tuple", ast.Dict: "a dict", ast.Set: "a set",
         ast.ListComp: "a comprehension", ast.GeneratorExp: "a comprehension", ast.JoinedStr: "a string",
         ast.Starred: "unpacking", ast.NamedExpr: "an assignment"}


def _size(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value or abs(value) > MAX_SIZE:
            raise ValueError("that number is too large")
    return value


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("that isn't a valid expression")
    return value


def _walk(node, names):
    match node:
        case ast.Expression():
            return _walk(node.body, names)
        case ast.Constant():
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("can't use a string in an expression" if isinstance(node.value, (str, bytes))
                                 else "can't use that constant in an expression")
            return _size(node.value)
        case ast.Name():
            if node.id not in names:
                raise ValueError(f"unknown name {node.id!r}")
            return _size(_number(names[node.id]))
        case ast.BinOp() if type(node.op) in _BINARY:
            left, right = _number(_walk(node.left, names)), _number(_walk(node.right, names))
            if isinstance(node.op, ast.Pow) and (abs(right) > 64 or abs(left) > 1_000_000):
                raise ValueError("that power is too large")
            try:
                result = _BINARY[type(node.op)](left, right)
            except ZeroDivisionError:
                raise ValueError("division by zero") from None
            except OverflowError:
                raise ValueError("that number is too large") from None
            if isinstance(result, complex):
                raise ValueError("that power has no real value")
            return _size(result)
        case ast.UnaryOp(op=ast.Not()):
            return not _walk(node.operand, names)
        case ast.UnaryOp(op=ast.USub() | ast.UAdd()):
            value = _number(_walk(node.operand, names))
            return -value if isinstance(node.op, ast.USub) else value
        case ast.BoolOp():
            want = isinstance(node.op, ast.Or)
            for v in node.values:  # short-circuits, so "b > 0 and a / b > 1" is safe
                if bool(_walk(v, names)) == want:
                    return want
            return not want
        case ast.Compare() if all(type(op) in _COMPARE for op in node.ops):
            left = _walk(node.left, names)
            for op, right_node in zip(node.ops, node.comparators):
                right = _walk(right_node, names)
                if not _COMPARE[type(op)](left, right):
                    return False
                left = right
            return True
        case ast.IfExp():
            return _walk(node.body if _walk(node.test, names) else node.orelse, names)
        case ast.Call():
            if not isinstance(node.func, ast.Name):
                raise ValueError(f"can't use {_WHAT.get(type(node.func), 'that call')} in an expression")
            if node.func.id not in FUNCTIONS:
                raise ValueError(f"unknown function {node.func.id!r}")
            if node.keywords:
                raise ValueError("functions take positional arguments only")
            args = [_number(_walk(a, names)) for a in node.args]
            try:
                return _size(FUNCTIONS[node.func.id](*args))
            except (TypeError, ValueError, ArithmeticError) as e:
                raise ValueError(str(e) if "too large" in str(e) or "needs" in str(e)
                                 else f"{node.func.id} can't take those arguments") from None
    raise ValueError(f"can't use {_WHAT.get(type(node), type(node).__name__.lower())} in an expression")


def evaluate(source: str, names: dict[str, int | float]) -> int | float | bool:
    if not isinstance(source, str) or not source.strip():
        raise ValueError("that isn't a valid expression")
    if len(source) > MAX_LEN:
        raise ValueError("that expression is too long")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError):
        raise ValueError("that isn't a valid expression") from None
    return _walk(tree, names)
