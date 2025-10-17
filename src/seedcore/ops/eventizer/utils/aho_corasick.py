#!/usr/bin/env python3
"""
Aho-Corasick Algorithm Implementation

Pure-Python implementation of the Aho-Corasick string matching algorithm
for efficient multi-pattern keyword matching. This serves as a fallback
when pyahocorasick is not available.

The Aho-Corasick algorithm builds a finite state machine that can match
multiple patterns simultaneously in a single pass through the text.
"""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional, Set, Tuple, Any, Iterator
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Match:
    """Represents a match found by the Aho-Corasick algorithm."""
    start: int
    end: int
    pattern: str
    pattern_id: str
    value: Any = None


class AhoCorasickNode:
    """Node in the Aho-Corasick trie."""
    
    def __init__(self):
        self.children: Dict[str, AhoCorasickNode] = {}
        self.failure_link: Optional[AhoCorasickNode] = None
        self.output_links: List[AhoCorasickNode] = []
        self.patterns: List[Tuple[str, str, Any]] = []  # (pattern, pattern_id, value)
        self.is_terminal: bool = False


class AhoCorasickTrie:
    """
    Pure-Python Aho-Corasick trie implementation.
    
    This implementation provides efficient multi-pattern string matching
    with O(n + m + z) time complexity where:
    - n = length of text
    - m = total length of all patterns
    - z = number of matches found
    """
    
    def __init__(self):
        self.root = AhoCorasickNode()
        self.pattern_count = 0
        self._built = False
    
    def add_pattern(self, pattern: str, pattern_id: str, value: Any = None) -> None:
        """
        Add a pattern to the trie.
        
        Args:
            pattern: The string pattern to match
            pattern_id: Unique identifier for the pattern
            value: Optional value associated with the pattern
        """
        if self._built:
            raise RuntimeError("Cannot add patterns after trie is built")
        
        if not pattern:
            return
        
        current = self.root
        for char in pattern:
            if char not in current.children:
                current.children[char] = AhoCorasickNode()
            current = current.children[char]
        
        current.patterns.append((pattern, pattern_id, value))
        current.is_terminal = True
        self.pattern_count += 1
    
    def build(self) -> None:
        """
        Build the failure links and output links for the trie.
        This must be called after adding all patterns and before searching.
        """
        if self._built:
            return
        
        # Build failure links using BFS
        from collections import deque
        queue = deque()
        
        # Initialize failure links for root's children
        for char, child in self.root.children.items():
            child.failure_link = self.root
            queue.append(child)
        
        # Build failure links for remaining nodes
        while queue:
            current = queue.popleft()
            
            for char, child in current.children.items():
                queue.append(child)
                
                # Find failure link for this child
                failure = current.failure_link
                while failure is not None and char not in failure.children:
                    failure = failure.failure_link
                
                if failure is not None and char in failure.children:
                    child.failure_link = failure.children[char]
                else:
                    child.failure_link = self.root
                
                # Build output links
                child.output_links = child.failure_link.output_links.copy()
                if child.is_terminal:
                    child.output_links.append(child)
        
        self._built = True
        logger.debug(f"Aho-Corasick trie built with {self.pattern_count} patterns")
    
    def search(self, text: str) -> Iterator[Match]:
        """
        Search for all patterns in the given text.
        
        Args:
            text: The text to search in
            
        Yields:
            Match objects for each pattern found
        """
        if not self._built:
            raise RuntimeError("Trie must be built before searching")
        
        current = self.root
        
        for i, char in enumerate(text):
            # Follow failure links until we find a child with this character
            while current is not None and char not in current.children:
                current = current.failure_link
            
            if current is not None and char in current.children:
                current = current.children[char]
            else:
                current = self.root
            
            # Check for matches at current node and output links
            if current.is_terminal:
                for pattern, pattern_id, value in current.patterns:
                    start = i - len(pattern) + 1
                    yield Match(
                        start=start,
                        end=i + 1,
                        pattern=pattern,
                        pattern_id=pattern_id,
                        value=value
                    )
            
            # Check output links for additional matches
            for output_node in current.output_links:
                for pattern, pattern_id, value in output_node.patterns:
                    start = i - len(pattern) + 1
                    yield Match(
                        start=start,
                        end=i + 1,
                        pattern=pattern,
                        pattern_id=pattern_id,
                        value=value
                    )
    
    def find_all(self, text: str) -> List[Match]:
        """
        Find all matches in the text and return as a list.
        
        Args:
            text: The text to search in
            
        Returns:
            List of Match objects
        """
        return list(self.search(text))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the trie."""
        def count_nodes(node: AhoCorasickNode) -> int:
            count = 1
            for child in node.children.values():
                count += count_nodes(child)
            return count
        
        return {
            "pattern_count": self.pattern_count,
            "node_count": count_nodes(self.root),
            "built": self._built
        }


class AhoCorasickMatcher:
    """
    High-level interface for Aho-Corasick pattern matching.
    
    This class provides a convenient interface for adding patterns
    and searching text, with support for case-insensitive matching
    and whole-word matching.
    """
    
    def __init__(self, case_sensitive: bool = True, whole_word: bool = False):
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.trie = AhoCorasickTrie()
        self._pattern_map: Dict[str, Dict[str, Any]] = {}
    
    def add_pattern(self, pattern: str, pattern_id: str, **kwargs) -> None:
        """
        Add a pattern to the matcher.
        
        Args:
            pattern: The string pattern to match
            pattern_id: Unique identifier for the pattern
            **kwargs: Additional metadata for the pattern
        """
        # Normalize pattern based on case sensitivity
        search_pattern = pattern if self.case_sensitive else pattern.lower()
        
        # Store pattern metadata
        self._pattern_map[pattern_id] = {
            "original_pattern": pattern,
            "search_pattern": search_pattern,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
            **kwargs
        }
        
        self.trie.add_pattern(search_pattern, pattern_id, self._pattern_map[pattern_id])
    
    def build(self) -> None:
        """Build the trie for searching."""
        self.trie.build()
    
    def search(self, text: str) -> Iterator[Match]:
        """
        Search for patterns in the text.
        
        Args:
            text: The text to search in
            
        Yields:
            Match objects for each pattern found
        """
        if not self.case_sensitive:
            text = text.lower()
        
        for match in self.trie.search(text):
            # Apply whole-word matching if enabled
            if self.whole_word and not self._is_whole_word(text, match.start, match.end):
                continue
            
            # Restore original pattern in match
            match.pattern = self._pattern_map[match.pattern_id]["original_pattern"]
            yield match
    
    def find_all(self, text: str) -> List[Match]:
        """
        Find all matches in the text.
        
        Args:
            text: The text to search in
            
        Returns:
            List of Match objects
        """
        return list(self.search(text))
    
    def _is_whole_word(self, text: str, start: int, end: int) -> bool:
        """Check if the match is a whole word."""
        # Check character before match
        if start > 0 and text[start - 1].isalnum():
            return False
        
        # Check character after match
        if end < len(text) and text[end].isalnum():
            return False
        
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the matcher."""
        stats = self.trie.get_stats()
        stats.update({
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
            "pattern_count": len(self._pattern_map)
        })
        return stats


# Optional pyahocorasick integration
try:
    import ahocorasick
    AHO_CORASICK_AVAILABLE = True
    logger.debug("pyahocorasick available, will use optimized implementation")
except ImportError:
    AHO_CORASICK_AVAILABLE = False
    logger.debug("pyahocorasick not available, using pure-Python implementation")


class OptimizedAhoCorasickMatcher:
    """
    Optimized Aho-Corasick matcher that uses pyahocorasick when available,
    falling back to pure-Python implementation.
    
    Supports budget controls, performance monitoring, and cross-domain pattern matching.
    """
    
    def __init__(self, case_sensitive: bool = True, whole_word: bool = False, 
                 budget_ms_soft: float = 40.0, budget_ms_hard: float = 100.0,
                 max_keywords_total: int = 200000):
        self.case_sensitive = case_sensitive
        self.whole_word = whole_word
        self.budget_ms_soft = budget_ms_soft
        self.budget_ms_hard = budget_ms_hard
        self.max_keywords_total = max_keywords_total
        self._pattern_map: Dict[str, Dict[str, Any]] = {}
        self._performance_stats = {
            "patterns_added": 0,
            "matches_found": 0,
            "total_time_ms": 0.0,
            "budget_exceeded": False
        }
        
        if AHO_CORASICK_AVAILABLE:
            self._automaton = ahocorasick.Automaton()
            self._use_optimized = True
        else:
            self._matcher = AhoCorasickMatcher(case_sensitive, whole_word)
            self._use_optimized = False
    
    def add_pattern(self, pattern: str, pattern_id: str, **kwargs) -> None:
        """Add a pattern to the matcher with budget controls."""
        # Check keyword limit
        if len(self._pattern_map) >= self.max_keywords_total:
            logger.warning(f"Keyword limit reached ({self.max_keywords_total}), skipping pattern {pattern_id}")
            return
        
        # Store pattern metadata with enhanced fields
        self._pattern_map[pattern_id] = {
            "original_pattern": pattern,
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
            "domains": kwargs.get("domains", []),
            "event_types": kwargs.get("event_types", []),
            "emits_tags": kwargs.get("emits_tags", []),
            "emits_attributes": kwargs.get("emits_attributes", {}),
            "priority": kwargs.get("priority", 100),
            "confidence": kwargs.get("confidence", 0.8),
            **kwargs
        }
        
        if self._use_optimized:
            search_pattern = pattern if self.case_sensitive else pattern.lower()
            self._automaton.add_word(search_pattern, (pattern_id, self._pattern_map[pattern_id]))
        else:
            self._matcher.add_pattern(pattern, pattern_id, **kwargs)
        
        self._performance_stats["patterns_added"] += 1
    
    def build(self) -> None:
        """Build the matcher for searching."""
        if self._use_optimized:
            self._automaton.make_automaton()
        else:
            self._matcher.build()
    
    def search(self, text: str, budget_ms: Optional[float] = None) -> Iterator[Match]:
        """Search for patterns in the text with optional budget control."""
        start_time = time.perf_counter()
        budget_ms = budget_ms or self.budget_ms_hard
        
        if self._use_optimized:
            yield from self._search_optimized(text, start_time, budget_ms)
        else:
            yield from self._search_with_budget(text, start_time, budget_ms)
    
    def _search_with_budget(self, text: str, start_time: float, budget_ms: float) -> Iterator[Match]:
        """Search with budget control for pure-Python implementation."""
        for match in self._matcher.search(text):
            current_time = time.perf_counter()
            elapsed_ms = (current_time - start_time) * 1000.0
            
            if elapsed_ms > budget_ms:
                self._performance_stats["budget_exceeded"] = True
                logger.debug(f"Search budget exceeded: {elapsed_ms:.2f}ms > {budget_ms}ms")
                break
            
            self._performance_stats["matches_found"] += 1
            yield match
    
    def _search_optimized(self, text: str, start_time: float, budget_ms: float) -> Iterator[Match]:
        """Search using pyahocorasick with budget control."""
        search_text = text if self.case_sensitive else text.lower()
        
        for end_index, (pattern_id, metadata) in self._automaton.iter(search_text):
            current_time = time.perf_counter()
            elapsed_ms = (current_time - start_time) * 1000.0
            
            if elapsed_ms > budget_ms:
                self._performance_stats["budget_exceeded"] = True
                logger.debug(f"Search budget exceeded: {elapsed_ms:.2f}ms > {budget_ms}ms")
                break
            
            start_index = end_index - len(metadata["original_pattern"]) + 1
            
            # Apply whole-word matching if enabled
            if self.whole_word and not self._is_whole_word(search_text, start_index, end_index + 1):
                continue
            
            self._performance_stats["matches_found"] += 1
            yield Match(
                start=start_index,
                end=end_index + 1,
                pattern=metadata["original_pattern"],
                pattern_id=pattern_id,
                value=metadata
            )
    
    def _is_whole_word(self, text: str, start: int, end: int) -> bool:
        """Check if the match is a whole word."""
        if start > 0 and text[start - 1].isalnum():
            return False
        if end < len(text) and text[end].isalnum():
            return False
        return True
    
    def find_all(self, text: str) -> List[Match]:
        """Find all matches in the text."""
        return list(self.search(text))
    
    def get_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics about the matcher."""
        base_stats = {
            "engine": "pyahocorasick" if self._use_optimized else "pure_python",
            "pattern_count": len(self._pattern_map),
            "case_sensitive": self.case_sensitive,
            "whole_word": self.whole_word,
            "budget_ms_soft": self.budget_ms_soft,
            "budget_ms_hard": self.budget_ms_hard,
            "max_keywords_total": self.max_keywords_total,
            "performance": self._performance_stats.copy()
        }
        
        if not self._use_optimized:
            base_stats.update(self._matcher.get_stats())
        
        return base_stats
    
    def get_domain_stats(self) -> Dict[str, Any]:
        """Get statistics grouped by domain."""
        domain_stats = {}
        for pattern_id, metadata in self._pattern_map.items():
            domains = metadata.get("domains", ["unknown"])
            for domain in domains:
                if domain not in domain_stats:
                    domain_stats[domain] = {
                        "pattern_count": 0,
                        "event_types": set(),
                        "total_priority": 0,
                        "avg_confidence": 0.0
                    }
                
                domain_stats[domain]["pattern_count"] += 1
                domain_stats[domain]["event_types"].update(metadata.get("event_types", []))
                domain_stats[domain]["total_priority"] += metadata.get("priority", 100)
                domain_stats[domain]["avg_confidence"] += metadata.get("confidence", 0.8)
        
        # Convert sets to lists and calculate averages
        for domain, stats in domain_stats.items():
            stats["event_types"] = list(stats["event_types"])
            if stats["pattern_count"] > 0:
                stats["avg_priority"] = stats["total_priority"] / stats["pattern_count"]
                stats["avg_confidence"] = stats["avg_confidence"] / stats["pattern_count"]
            del stats["total_priority"]
        
        return domain_stats
    
    def reset_performance_stats(self) -> None:
        """Reset performance statistics."""
        self._performance_stats = {
            "patterns_added": 0,
            "matches_found": 0,
            "total_time_ms": 0.0,
            "budget_exceeded": False
        }


# Convenience function for creating matchers
def create_keyword_matcher(case_sensitive: bool = True, whole_word: bool = False,
                          budget_ms_soft: float = 40.0, budget_ms_hard: float = 100.0,
                          max_keywords_total: int = 200000) -> OptimizedAhoCorasickMatcher:
    """
    Create an optimized Aho-Corasick keyword matcher with budget controls.
    
    Args:
        case_sensitive: Whether matching should be case-sensitive
        whole_word: Whether matches should be whole words only
        budget_ms_soft: Soft budget limit in milliseconds
        budget_ms_hard: Hard budget limit in milliseconds
        max_keywords_total: Maximum number of keywords allowed
        
    Returns:
        OptimizedAhoCorasickMatcher instance
    """
    return OptimizedAhoCorasickMatcher(
        case_sensitive=case_sensitive, 
        whole_word=whole_word,
        budget_ms_soft=budget_ms_soft,
        budget_ms_hard=budget_ms_hard,
        max_keywords_total=max_keywords_total
    )
