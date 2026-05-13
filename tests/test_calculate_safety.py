"""Security tests for safe_calculate — verifies AST whitelist blocks attacks."""
import pytest
from seekflow.agent.agent import safe_calculate


class TestSafeCalculate:
    """Valid expressions must produce correct numeric results."""

    def test_simple_addition(self):
        result = safe_calculate("2 + 3")
        assert result.startswith("Result: 5")

    def test_complex_expression(self):
        result = safe_calculate("(8630 - 3120) / 8630")
        assert result.startswith("Result: 0.6385")

    def test_unary_negation(self):
        result = safe_calculate("-42")
        assert result.startswith("Result: -42")

    def test_builtin_abs(self):
        result = safe_calculate("abs(-5)")
        assert result.startswith("Result: 5")

    def test_builtin_round(self):
        result = safe_calculate("round(3.14159, 2)")
        assert result.startswith("Result: 3.14")

    def test_builtin_min(self):
        result = safe_calculate("min(10, 5, 8)")
        assert result.startswith("Result: 5")

    def test_builtin_max(self):
        result = safe_calculate("max(10, 5, 8)")
        assert result.startswith("Result: 10")

    def test_builtin_sum(self):
        # sum() needs a list/tuple literal — both are safe container literals
        result = safe_calculate("sum([1, 2, 3])")
        assert result.startswith("Result: 6")

    def test_builtin_pow(self):
        result = safe_calculate("pow(2, 10)")
        assert result.startswith("Result: 1024")

    def test_float_literal(self):
        result = safe_calculate("3.14 * 2")
        assert result.startswith("Result: 6.28")

    def test_integer_division(self):
        result = safe_calculate("7 // 2")
        assert result.startswith("Result: 3")

    def test_modulo(self):
        result = safe_calculate("10 % 3")
        assert result.startswith("Result: 1")


class TestAttackVectors:
    """Every attack vector must return 'Calculation error:' — never execute."""

    ATTACKS = [
        # Code injection
        "__import__('os').system('rm -rf /')",
        "__import__('subprocess').call(['echo', 'pwned'])",
        "exec('print(1)')",
        "eval('1+1')",
        "compile('print(1)', '', 'exec')",
        # Attribute access / class traversal
        "().__class__.__bases__[0].__subclasses__()",
        "'abc'.__class__.__mro__[1].__subclasses__()",
        # File I/O
        "open('/etc/passwd').read()",
        "__builtins__.open('/etc/passwd')",
        # Comprehensions (ListComp/DictComp/SetComp are NOT ast.List — rejected)
        "[x for x in range(10)]",
        "{x: x*2 for x in range(5)}",
        "{x for x in range(5)}",
        # Generator expression (not in whitelist)
        "(x for x in range(5))",
        # Lambda
        "lambda x: x + 1",
        # Assignment / walrus
        "x = 5",
        "(x := 5)",
        # Attribute access on numbers
        "(1).__class__",
        # Unapproved function calls
        "len('test')",
        "range(10)",
        "type(1)",
        "isinstance(1, int)",
        "getattr({}, 'keys')",
        "setattr({}, 'x', 1)",
        # Boolean operators (not arithmetic)
        "1 and 2",
        "1 or 2",
        "not True",
        # Comparison operators (not arithmetic)
        "1 < 2",
        "1 == 1",
        "1 != 2",
    ]

    @pytest.mark.parametrize("attack", ATTACKS)
    def test_attack_rejected(self, attack: str):
        result = safe_calculate(attack)
        assert result.startswith("Calculation error:"), (
            f"DANGER: attack vector NOT rejected!\n"
            f"  Input:  {attack}\n"
            f"  Output: {result}"
        )


class TestEdgeCases:
    def test_empty_input(self):
        result = safe_calculate("")
        assert result.startswith("Calculation error:")

    def test_whitespace_only(self):
        result = safe_calculate("   \n  ")
        assert result.startswith("Calculation error:")

    def test_non_expression_statement(self):
        result = safe_calculate("if True: print(1)")
        assert result.startswith("Calculation error:")

    def test_multi_statement(self):
        result = safe_calculate("1; 2")
        assert result.startswith("Calculation error:")
