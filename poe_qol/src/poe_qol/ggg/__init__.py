"""Official Path of Exile developer API (pathofexile.com/developer/docs).

* :mod:`.oauth`: OAuth 2.1 authorization-code + PKCE sign-in for a
  *public* (desktop) client, with a loopback redirect.
* :mod:`.token_store`: keeps the token on disk, encrypted with Windows
  DPAPI on Windows.
* :mod:`.ratelimit`: obeys GGG's ``X-Rate-Limit-*`` headers.
* :mod:`.api`: the account endpoints the Wealth tab needs
  (profile, leagues, stashes).

Only documented endpoints are called, only with a token the player
granted on pathofexile.com, and only when the player asked for a sync
(or switched on automatic sync).
"""
