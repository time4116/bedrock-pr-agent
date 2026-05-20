"""
Logging utility for the application.

Provides standardized JSON logging with automatic PR context injection.
All logs are output as valid JSON with consistent structure.
"""
import os
import json
from datetime import datetime
from typing import Dict, Any, Optional
from contextvars import ContextVar

# Context variable to store PR metadata across the execution
_pr_context: ContextVar[Optional[Dict[str, Any]]] = ContextVar('pr_context', default=None)


class Logger:
    """
    Standardized JSON logger for Lambda functions and AgentCore.
    
    All logs are output as valid JSON with consistent structure:
    {
        "timestamp": "ISO-8601",
        "level": "INFO|ERROR|WARNING|DEBUG",
        "message": "Human-readable message",
        "pr_number": 123,  # Always included if set
        "repo": "owner/repo",  # Always included if set
        "context": {...}  # Additional metadata
    }
    """
    
    LOG_LEVELS = {
        'debug': 0,
        'info': 1,
        'warn': 2,
        'warning': 2,
        'error': 3
    }
    
    def __init__(self):
        """Initialize logger with log level from environment."""
        self.log_level = os.environ.get('LOG_LEVEL', 'info').lower()
    
    def set_pr_context(
        self,
        pr_number: Optional[int] = None,
        repo: Optional[str] = None,
        branch: Optional[str] = None,
        installation_id: Optional[int] = None
    ) -> None:
        """
        Set PR context for all subsequent logs in this execution.
        
        This should be called once at the start of PR processing.
        All logs will automatically include this context.
        
        Args:
            pr_number: GitHub PR number
            repo: Repository full name (owner/repo)
            branch: Branch name
            installation_id: GitHub App installation ID
        """
        context = {}
        if pr_number is not None:
            context['pr_number'] = pr_number
        if repo:
            context['repo'] = repo
        if branch:
            context['branch'] = branch
        if installation_id is not None:
            context['installation_id'] = installation_id
        
        _pr_context.set(context if context else None)
    
    def clear_pr_context(self) -> None:
        """Clear PR context (useful for testing or between invocations)."""
        _pr_context.set(None)
    
    def _should_log(self, level: str) -> bool:
        """Check if message should be logged based on level."""
        current_level = self.LOG_LEVELS.get(self.log_level, 1)
        message_level = self.LOG_LEVELS.get(level, 1)
        return message_level >= current_level
    
    def _format_message(
        self,
        level: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format log message as valid JSON with PR context.
        
        Args:
            level: Log level (debug, info, warn, error)
            message: Human-readable message
            context: Additional context to include
            
        Returns:
            JSON-formatted log string
        """
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': level.upper(),
            'message': message
        }
        
        # Always include PR context if available
        pr_ctx = _pr_context.get()
        if pr_ctx:
            log_entry.update(pr_ctx)
        
        # Merge additional context
        if context:
            # If context has pr_number or repo, it overrides the global context
            log_entry.update(context)
        
        return json.dumps(log_entry, default=str, ensure_ascii=False)
    
    def debug(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log debug message as valid JSON."""
        if self._should_log('debug'):
            print(self._format_message('debug', message, context), flush=True)
    
    def info(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log info message as valid JSON."""
        if self._should_log('info'):
            print(self._format_message('info', message, context), flush=True)
    
    def warn(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log warning message as valid JSON."""
        if self._should_log('warn'):
            print(self._format_message('warn', message, context), flush=True)
    
    def warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log warning message as valid JSON (alias for warn)."""
        self.warn(message, context)
    
    def error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Log error message as valid JSON."""
        if self._should_log('error'):
            print(self._format_message('error', message, context), flush=True)


# Global logger instance
logger = Logger()
