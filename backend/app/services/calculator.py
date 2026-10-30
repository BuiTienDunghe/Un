"""Exact arithmetic for the agent. It walks the parsed expression and allows numbers and the
listed operators only, so no name, call or attribute can run, and it refuses a power that
would freeze the turn. Decimal keeps money exact: 0.1 + 0.2 is 0.3 here."""
from __future__ import annotations

import ast
import operator
from decimal import Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext

MAX_EXPRESSION_CHARS = 200
MAX_EXPONENT = 64
MAX_ABS_RESULT = Decimal(10) ** 60
_BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class CalculationError(ValueError):
    pass


def _evaluate(node: ast.AST) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        # repr, not the float itself: Decimal(0.1) would carry the binary error along.
        return Decimal(repr(node.value))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_evaluate(node.operand))
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left), _evaluate(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT:
                raise CalculationError(f"Số mũ lớn nhất là {MAX_EXPONENT}.")
            return left**right
        if type(node.op) in _BINARY:
            return _BINARY[type(node.op)](left, right)
    raise CalculationError("Chỉ dùng số, + - * / // % ** và dấu ngoặc.")


def calculate(expression: str) -> str:
    """The value as plain digits with no trailing zeros, or CalculationError saying what to fix."""
    text = expression.strip()
    if not text or len(text) > MAX_EXPRESSION_CHARS:
        raise CalculationError(f"Biểu thức phải có từ 1 đến {MAX_EXPRESSION_CHARS} ký tự.")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as error:
        raise CalculationError("Biểu thức sai cú pháp. Viết số kiểu 1250000 hoặc 7.5, không có dấu phân cách nghìn.") from error
    with localcontext() as context:
        context.prec = 80
        try:
            value = _evaluate(tree)
        except (DivisionByZero, ZeroDivisionError) as error:
            raise CalculationError("Không chia được cho 0.") from error
        except (InvalidOperation, Overflow, RecursionError) as error:
            raise CalculationError("Không tính được biểu thức này.") from error
        if abs(value) > MAX_ABS_RESULT:
            raise CalculationError("Kết quả quá lớn.")
        rounded = round(value, 12).normalize()
    return format(rounded, "f")
