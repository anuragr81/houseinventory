"""
app/domain/facet_catalogue.py
-----------------------------
The facet vocabulary the platform owns.

`CLAUDE.md`: "Members rate real-world venues on a schema **the platform
owns**." This module is what makes that structurally true rather than
aspirational. A founder *selects* facets by key; they cannot author a facet
name, because names exist only here.

**Why this is a privacy control and not just tidiness.** A user-authored facet
name would be the first thing in this system that is user-written, persisted
indefinitely, and published -- everything else is either transient
(`RawContribution`, purged on fold) or numeric (`FacetStat`). That combination
is what lets a name carry a third party's personal data ("how good is
<named person>'s bedside manner"), published with community ratings attached,
about someone who never consented and has no erasure path. A controlled
vocabulary removes the possibility rather than promising to moderate it.

It does **not** close the whole hole: `Community.slug` is still user-supplied,
persisted, and published. That surface is much smaller and structurally
constrained, but it is why the operational takedown channel is still needed.
See the facet-vocabulary invariant in `docs/04_PRIVACY_INVARIANTS.md`.

**There is deliberately no default catalogue.** Which facets a wine-lover
rates versus a cricketer is per-community facet content, explicitly out of
scope for the bootstrap (`docs/00_BOOTSTRAP.md`), and a plausible-looking
default is how an open decision silently becomes a shipped one. This follows
`CohortBucketing`, which has no default instance for the same reason.
"""

from dataclasses import dataclass

from app.domain.enums import FacetValueType

# Value types the aggregation path can actually carry. `FacetStat` is a
# mean/variance/n triple over floats, so:
#   NUMERIC  -- the intended case.
#   BOOLEAN  -- 0/1, whose mean is the proportion. Meaningful.
#   ORDINAL  -- arithmetically fine, statistically dubious (the mean of rank
#               positions is not a rank). Permitted, and flagged under OPEN-3
#               along with the rest of the FacetStat shape.
#   TEXT     -- refused. There is no path from text to a float, and the only
#               way to make one would persist per-contribution prose, which is
#               exactly what INV-RAW-3 forbids. Declaring a TEXT facet is a
#               promise the system cannot keep.
SCOREABLE_VALUE_TYPES = frozenset(
    {FacetValueType.NUMERIC, FacetValueType.BOOLEAN, FacetValueType.ORDINAL}
)


class FacetCatalogueError(Exception):
    """The catalogue was built or queried in a way that cannot be honoured."""


class UnknownFacetKeyError(FacetCatalogueError):
    """A key was requested that the catalogue does not define."""


@dataclass(frozen=True)
class FacetDefinition:
    """One facet the platform offers, addressable by a stable key.

    `key` is what a request carries; `name` is what the platform publishes.
    Keeping them separate means the display name can be corrected -- including
    in response to a takedown -- without invalidating every stored reference
    to it.
    """

    key: str
    name: str
    value_type: FacetValueType
    scale_min: float | None = None
    scale_max: float | None = None

    def __post_init__(self) -> None:
        if not self.key:
            raise FacetCatalogueError("A facet definition needs a key.")
        if not self.name:
            raise FacetCatalogueError(f"Facet {self.key!r} needs a name.")
        if self.value_type not in SCOREABLE_VALUE_TYPES:
            raise FacetCatalogueError(
                f"Facet {self.key!r} has value type {self.value_type}, which the "
                f"aggregation path cannot score. See SCOREABLE_VALUE_TYPES."
            )
        if self.value_type is FacetValueType.NUMERIC and (
            self.scale_min is None or self.scale_max is None
        ):
            raise FacetCatalogueError(
                f"Numeric facet {self.key!r} needs both scale_min and scale_max: "
                f"an unbounded rating scale cannot be compared across venues."
            )
        if (
            self.scale_min is not None
            and self.scale_max is not None
            and self.scale_min >= self.scale_max
        ):
            raise FacetCatalogueError(
                f"Facet {self.key!r} has scale_min >= scale_max."
            )


@dataclass(frozen=True)
class FacetCatalogue:
    """The set of facets a community may choose from.

    No default instance, on purpose -- see the module docstring.
    """

    definitions: tuple[FacetDefinition, ...]

    def __post_init__(self) -> None:
        if not self.definitions:
            raise FacetCatalogueError("A catalogue with no facets can found nothing.")
        keys = [definition.key for definition in self.definitions]
        if len(set(keys)) != len(keys):
            raise FacetCatalogueError("Facet keys must be unique within a catalogue.")

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(definition.key for definition in self.definitions)

    def resolve(self, keys: frozenset[str] | set[str]) -> tuple[FacetDefinition, ...]:
        """The definitions for `keys`, or raise naming how many were unknown.

        The message counts rather than lists them: an error body must not
        echo caller-supplied strings back out (`docs/03_API_CONTRACT.md`),
        and a key is caller-supplied.
        """
        unknown = set(keys) - self.keys
        if unknown:
            raise UnknownFacetKeyError(
                f"{len(unknown)} requested facet(s) are not in the platform "
                f"catalogue."
            )
        return tuple(
            definition for definition in self.definitions if definition.key in keys
        )
