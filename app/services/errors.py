class UnknownThemeError(Exception):
    """Raised when a report is requested for a theme not in the taxonomy.

    Translated to HTTP 404 by the API exception handler (see app/main.py)."""
