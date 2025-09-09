"""
Safe predicate expression evaluator using AST parsing.

This module provides a secure way to evaluate boolean expressions in predicates
without using eval(), ensuring only safe operations are allowed.
"""

import ast
import operator
import logging
from typing import Dict, Any, Union, List

logger = logging.getLogger(__name__)

class PredicateEvaluator:
    """Safe evaluator for predicate expressions."""
    
    def __init__(self):
        # Safe operators mapping
        self.operators = {
            # Boolean operators
            ast.And: self._and_op,
            ast.Or: self._or_op,
            ast.Not: self._not_op,
            
            # Comparison operators
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
            ast.Is: operator.is_,
            ast.IsNot: operator.is_not,
            ast.In: self._in_op,
            ast.NotIn: self._not_in_op,
            
            # Arithmetic operators
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
            
            # Unary operators
            ast.UAdd: operator.pos,
            ast.USub: operator.neg,
        }
    
    def eval_predicate(self, expr: str, context: Dict[str, Any]) -> bool:
        """
        Evaluate a predicate expression safely.
        
        Args:
            expr: Boolean expression string
            context: Variable context for evaluation
            
        Returns:
            Boolean result of expression evaluation
            
        Raises:
            ValueError: If expression is invalid or contains unsafe operations
        """
        try:
            # Parse the expression
            tree = ast.parse(expr, mode='eval')
            
            # Evaluate the expression
            result = self._eval_node(tree.body, context)
            
            # Ensure result is boolean
            if isinstance(result, bool):
                return result
            else:
                logger.warning(f"Expression '{expr}' returned non-boolean result: {result}")
                return bool(result)
                
        except Exception as e:
            logger.error(f"Failed to evaluate expression '{expr}': {e}")
            raise ValueError(f"Invalid expression: {expr}") from e
    
    def _eval_node(self, node: ast.AST, context: Dict[str, Any]) -> Any:
        """Recursively evaluate AST nodes."""
        
        # Literals
        if isinstance(node, ast.Constant):
            return node.value
        
        # Names (variables)
        if isinstance(node, ast.Name):
            if node.id in context:
                return context[node.id]
            else:
                raise ValueError(f"Undefined variable: {node.id}")
        
        # Attribute access (e.g., task.type)
        if isinstance(node, ast.Attribute):
            obj = self._eval_node(node.value, context)
            if isinstance(obj, dict):
                return obj.get(node.attr)
            else:
                raise ValueError(f"Cannot access attribute {node.attr} on {type(obj)}")
        
        # Subscript access (e.g., list[0])
        if isinstance(node, ast.Subscript):
            obj = self._eval_node(node.value, context)
            key = self._eval_node(node.slice, context)
            if isinstance(obj, (list, tuple)) and isinstance(key, int):
                return obj[key]
            elif isinstance(obj, dict):
                return obj.get(key)
            else:
                raise ValueError(f"Cannot subscript {type(obj)} with {type(key)}")
        
        # Boolean operations
        if isinstance(node, ast.BoolOp):
            values = [self._eval_node(v, context) for v in node.values]
            if isinstance(node.op, ast.And):
                return self._and_op(values)
            elif isinstance(node.op, ast.Or):
                return self._or_op(values)
        
        # Unary operations
        if isinstance(node, ast.UnaryOp):
            operand = self._eval_node(node.operand, context)
            if isinstance(node.op, ast.Not):
                return self._not_op(operand)
            elif isinstance(node.op, ast.UAdd):
                return self._uadd_op(operand)
            elif isinstance(node.op, ast.USub):
                return self._usub_op(operand)
        
        # Binary operations
        if isinstance(node, ast.BinOp):
            left = self._eval_node(node.left, context)
            right = self._eval_node(node.right, context)
            op_func = self.operators.get(type(node.op))
            if op_func:
                return op_func(left, right)
            else:
                raise ValueError(f"Unsupported binary operator: {type(node.op)}")
        
        # Comparison operations
        if isinstance(node, ast.Compare):
            left = self._eval_node(node.left, context)
            result = True
            
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_node(comparator, context)
                op_func = self.operators.get(type(op))
                if op_func:
                    if not op_func(left, right):
                        result = False
                        break
                else:
                    raise ValueError(f"Unsupported comparison operator: {type(op)}")
                left = right
            
            return result
        
        # List/tuple literals
        if isinstance(node, ast.List):
            return [self._eval_node(elt, context) for elt in node.elts]
        
        if isinstance(node, ast.Tuple):
            return tuple(self._eval_node(elt, context) for elt in node.elts)
        
        # Dictionary literals
        if isinstance(node, ast.Dict):
            return {
                self._eval_node(k, context): self._eval_node(v, context)
                for k, v in zip(node.keys, node.values)
            }
        
        # Slice objects
        if isinstance(node, ast.Slice):
            lower = self._eval_node(node.lower, context) if node.lower else None
            upper = self._eval_node(node.upper, context) if node.upper else None
            step = self._eval_node(node.step, context) if node.step else None
            return slice(lower, upper, step)
        
        # Index objects
        if isinstance(node, ast.Index):
            return self._eval_node(node.value, context)
        
        # If expressions (ternary operator)
        if isinstance(node, ast.IfExp):
            test = self._eval_node(node.test, context)
            if test:
                return self._eval_node(node.body, context)
            else:
                return self._eval_node(node.orelse, context)
        
        # Unsupported node types
        raise ValueError(f"Unsupported AST node type: {type(node)}")
    
    def _and_op(self, values: Union[bool, List[Any]]) -> bool:
        """Logical AND operation."""
        if isinstance(values, list):
            return all(bool(v) for v in values)
        return bool(values)
    
    def _or_op(self, values: Union[bool, List[Any]]) -> bool:
        """Logical OR operation."""
        if isinstance(values, list):
            return any(bool(v) for v in values)
        return bool(values)
    
    def _not_op(self, value: Any) -> bool:
        """Logical NOT operation."""
        return not bool(value)
    
    def _in_op(self, left: Any, right: Any) -> bool:
        """IN operation."""
        try:
            return left in right
        except TypeError:
            return False
    
    def _not_in_op(self, left: Any, right: Any) -> bool:
        """NOT IN operation."""
        try:
            return left not in right
        except TypeError:
            return True
    
    def _uadd_op(self, value: Any) -> Any:
        """Unary plus operation."""
        return +value
    
    def _usub_op(self, value: Any) -> Any:
        """Unary minus operation."""
        return -value

# Global evaluator instance
_evaluator = PredicateEvaluator()

def eval_predicate(expr: str, context: Dict[str, Any]) -> bool:
    """Convenience function to evaluate a predicate expression."""
    return _evaluator.eval_predicate(expr, context)

def validate_expression(expr: str) -> bool:
    """Validate that an expression can be parsed without evaluating it."""
    try:
        tree = ast.parse(expr, mode='eval')
        return True
    except Exception:
        return False
