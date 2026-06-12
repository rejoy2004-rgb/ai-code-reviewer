import asyncio
import logging
import random
import time
from functools import wraps
from typing import Callable, Any, TypeVar

logger = logging.getLogger("app.rate_limiter")

T = TypeVar("T")


class AsyncRateLimiter:
    """
    A simple token bucket rate limiter to throttle async requests.
    Enforces a maximum number of requests per period (e.g., 15 requests per 60 seconds).
    """
    def __init__(self, max_requests: int = 15, period: float = 60.0):
        self.max_requests = max_requests
        self.period = period
        self.tokens = float(max_requests)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Acquires a token, sleeping if none are available."""
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                
                # Add tokens based on elapsed time
                self.tokens = min(self.max_requests, self.tokens + elapsed * (self.max_requests / self.period))
                
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                
                # Wait for the next token to be available
                wait_time = (1.0 - self.tokens) * (self.period / self.max_requests)
                logger.debug(f"Rate limit hit. Throttling request. Sleeping for {wait_time:.2f}s")
                await asyncio.sleep(wait_time)


# Global rate limiter instance for Gemini API to respect 15 RPM
gemini_rate_limiter = AsyncRateLimiter(max_requests=12, period=60.0) # slightly under 15 to be safe


def async_retry(
    max_retries: int = 5,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (Exception,)
):
    """
    Decorator to retry an async function with exponential backoff and jitter.
    Especially useful for handling 429 (Rate Limit) and 5xx (Server Error) responses.
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = initial_delay
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as e:
                    exc_name = e.__class__.__name__
                    err_msg = str(e)
                    
                    # Detect if it's a rate limit or transient error
                    is_rate_limit = "429" in err_msg or "ResourceExhausted" in exc_name or "quota" in err_msg.lower() or "rate limit" in err_msg.lower()
                    is_transient = "500" in err_msg or "502" in err_msg or "503" in err_msg or "504" in err_msg or "timeout" in err_msg.lower()
                    
                    # If it's not a rate limit or transient error, and we aren't retrying all exceptions, raise
                    if not (is_rate_limit or is_transient) and retryable_exceptions == (Exception,):
                        # Keep retrying since default is any Exception
                        pass
                    elif not (is_rate_limit or is_transient):
                        logger.error(f"Non-retryable exception encountered: {exc_name} - {err_msg}")
                        raise e

                    if attempt == max_retries:
                        logger.error(f"Failed after {max_retries} attempts. Last exception: {exc_name} - {err_msg}")
                        raise e

                    # Calculate sleep delay
                    sleep_time = delay
                    if jitter:
                        sleep_time = delay * random.uniform(0.5, 1.5)

                    logger.warning(
                        f"Attempt {attempt} failed with {exc_name}: {err_msg}. "
                        f"Retrying in {sleep_time:.2f} seconds..."
                    )
                    await asyncio.sleep(sleep_time)
                    delay *= backoff_factor
            
        return wrapper
    return decorator
