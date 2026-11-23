"""Experimental features that do NOT follow GGG's third-party rules.

Everything in this package is opt-in, off by default, and must be
explicitly acknowledged in the UI before it runs. Nothing outside this
package imports it at module load time; the area-select controller
imports it lazily, only when the experimental transfer mode is active.

GGG (https://www.pathofexile.com/developer/docs) allows a macro to
perform at most one game action per key press, and no timer-driven
input. Modules here break that rule on purpose, for the owner's personal
use, and can get an account actioned. See docs/COMPLIANCE_REVIEW.md §7.
"""
