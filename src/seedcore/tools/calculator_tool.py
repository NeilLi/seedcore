#!/usr/bin/env python
# seedcore/tools/calculator_tool.py

"""
Calculator Tool for safe arithmetic evaluation.

This tool provides safe arithmetic evaluation using AST parsing,
replacing unsafe eval() calls with a restricted set of allowed operations.
"""

from __future__ import annotations
from typing import Dict, Any
import logging
import ast
import operator

logger = logging.getLogger(__name__)

# Safe arithmetic operations allowed
_ALLOWED_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


class CalculatorTool:
    """
    A safe arithmetic calculator tool.
    
    Evaluates simple arithmetic expressions safely via AST parsing.
    Supports + - * / // % ** and unary +/- on numbers.
    No names, no function calls, no side effects.
    """
    
    @property
    def name(self) -> str:
        return "calculator.evaluate"
    
    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": "Evaluates a simple arithmetic expression safely. Supports + - * / // % ** and unary +/- on numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The arithmetic expression to evaluate (e.g., '2 + 3 * 4', '10 / 2', '2 ** 8').",
                    }
                },
                "required": ["expression"],
            }
        }
    
    def _eval(self, node: ast.AST) -> float:
        """
        Recursively evaluate an AST node.
        
        Args:
            node: The AST node to evaluate
            
        Returns:
            The numeric result
            
        Raises:
            ValueError: If the expression contains unsupported operations or non-numeric values
        """
        if isinstance(node, ast.Num):  # Python < 3.8
            return node.n
        if isinstance(node, ast.Constant):  # Python >= 3.8
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("Only numeric constants allowed")
        if isinstance(node, ast.BinOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError("Operator not allowed")
            return op(self._eval(node.left), self._eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _ALLOWED_OPS.get(type(node.op))
            if not op:
                raise ValueError("Unary operator not allowed")
            return op(self._eval(node.operand))
        raise ValueError("Unsupported expression")
    
    async def execute(self, expression: str) -> float:
        """
        Execute the arithmetic evaluation.
        
        Args:
            expression: The arithmetic expression to evaluate
            
        Returns:
            The numeric result as a float
            
        Raises:
            ValueError: If the expression is invalid or contains unsupported operations
        """
        if not expression or not isinstance(expression, str):
            raise ValueError("Expression must be a non-empty string")
        
        try:
            tree = ast.parse(expression, mode="eval")
            result = self._eval(tree.body)
            return float(result)
        except SyntaxError as e:
            logger.warning(f"Invalid arithmetic expression syntax: {expression}")
            raise ValueError(f"Invalid expression syntax: {e}") from e
        except ValueError as e:
            logger.warning(f"Unsafe or unsupported expression: {expression}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error evaluating expression '{expression}': {e}")
            raise ValueError(f"Failed to evaluate expression: {e}") from e


# ============================================================
# Registration
# ============================================================

async def register_calculator_tool(tool_manager) -> None:
    """
    Register the calculator tool with the ToolManager.
    
    Args:
        tool_manager: The ToolManager instance to register with
    """
    await tool_manager.register("calculator.evaluate", CalculatorTool())
    logger.info("Registered calculator tool")

