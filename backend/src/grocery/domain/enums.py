from enum import StrEnum


class ClientRegistration(StrEnum):
    CIMD = "cimd"
    DCR = "dcr"


class MemberRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"


class AddStatus(StrEnum):
    CREATED = "created"
    MERGED = "merged"


class EventType(StrEnum):
    ITEMS_ADDED = "items_added"
    ITEM_UPDATED = "item_updated"
    ITEMS_BOUGHT = "items_bought"
    ITEMS_UNBOUGHT = "items_unbought"
    ITEMS_DELETED = "items_deleted"
    BOUGHT_CLEARED = "bought_cleared"
    TAG_CREATED = "tag_created"
    TAG_RENAMED = "tag_renamed"
    TAGS_MERGED = "tags_merged"
    TAG_DELETED = "tag_deleted"
