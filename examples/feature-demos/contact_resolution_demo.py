"""
Contact resolution -- ContactManager.identify_contact_method choosing among
several registered methods.

With one contact method registered, identify_contact_method returns it
directly. With several, an LLM picks among them, weighing each method's
`preference` (lower = more favored), whether it is asynchronous (email/webhook/
notification), the user's stated preferred_channel/working_hours, and
out_of_office -- preferring an asynchronous method when the user is out of
office or outside working hours. An optional `topic` layers an
availability.by_topic override on top of the general availability.* settings.

Run from examples/feature-demos/:
    python3 contact_resolution_demo.py
"""
import asyncio
from pathlib import Path

from blue_data_user_source.data.manager import CLS_JSON_MEMORY, CLS_KB_MEMORY, UserDataManager
from blue_data_user_source.interaction.contact import ContactManager

DIVIDER = "-" * 60
_DATA_DIR = Path(__file__).parent.parent.parent / "lib" / "src" / "blue_data_user_source" / "data"
_MEM_JSON = {"_class": CLS_JSON_MEMORY, "connection": {"protocol": "json/memory"}}
_MEM_KB = {"_class": CLS_KB_MEMORY, "connection": {"protocol": "kb/memory"}}


async def build_manager() -> UserDataManager:
    manager = UserDataManager("alice", _MEM_JSON)
    await manager.build(
        schema_path=str(_DATA_DIR / "schema.json"),
        kb_source_props=_MEM_KB,
        metadata_schema_path=str(_DATA_DIR / "metadata_schema.json"),
        metadata_source_props=_MEM_JSON,
        contact_schema_path=str(_DATA_DIR / "contact_schema.json"),
        contact_source_props=_MEM_JSON,
        session_source_props=_MEM_JSON,
    )
    return manager


async def main():
    manager = await build_manager()
    contacts = ContactManager(database="alice", data_manager=manager)

    print(DIVIDER)
    print("1. A single registered method is returned directly (no LLM call)")
    print(DIVIDER)
    await contacts.create_contact_method("stdio", "terminal", details={}, preference=0)
    method = await contacts.identify_contact_method()
    print(f"  -> {method.protocol}/{method.name}")

    print()
    print(DIVIDER)
    print("2. Several methods -- preference + availability decide")
    print(DIVIDER)
    await contacts.create_contact_method(
        "email", "work", details={"address": "alice@example.com"}, preference=1,
    )
    await contacts.create_contact_method(
        "webhook", "chatbot", details={"url": "https://example.com/hook",
                                        "response_base_url": "http://localhost:8000"},
        preference=2,
    )
    manager.set_metadata("identity.timezone", "America/New_York")
    manager.set_metadata("availability.working_hours", "09:00-17:00 Mon-Fri")
    manager.set_metadata("availability.out_of_office", False)
    method = await contacts.identify_contact_method()
    print("  In office, within working hours ->", f"{method.protocol}/{method.name}")

    print()
    print(DIVIDER)
    print("3. out_of_office=True -- prefers an asynchronous method")
    print(DIVIDER)
    manager.set_metadata("availability.out_of_office", True)
    method = await contacts.identify_contact_method()
    print("  Out of office ->", f"{method.protocol}/{method.name}",
          f"(is_async={method.is_async})")

    print()
    print(DIVIDER)
    print("4. availability.by_topic override")
    print(DIVIDER)
    manager.set_metadata("availability.out_of_office", False)
    manager.set_metadata("availability.preferred_channel", "webhook")
    manager.set_metadata("availability.by_topic", {
        "billing": {"preferred_channel": "email", "out_of_office": True},
    })
    method_general = await contacts.identify_contact_method()
    method_billing = await contacts.identify_contact_method(topic="billing")
    print("  No topic (general preferred_channel=webhook) ->",
          f"{method_general.protocol}/{method_general.name}")
    print("  topic='billing' (overrides to preferred_channel=email, out_of_office=True) ->",
          f"{method_billing.protocol}/{method_billing.name}",
          f"(is_async={method_billing.is_async})")


asyncio.run(main())
