import asyncio
import importlib
import json
import sys
import types
from enum import IntFlag
from pathlib import Path
from types import SimpleNamespace


class _MediaPlayerEntityFeature(IntFlag):
    BROWSE_MEDIA = 1
    PLAY = 2
    PAUSE = 4
    NEXT_TRACK = 8
    PREVIOUS_TRACK = 16
    VOLUME_SET = 32
    VOLUME_STEP = 64
    VOLUME_MUTE = 128
    PLAY_MEDIA = 256
    SEEK = 512


def _load_media_player_module(monkeypatch):
    async def async_publish(*args):
        pass

    async def async_subscribe(*args):
        pass

    async def async_wait_for_mqtt_client(*args):
        return True

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    media_source = types.ModuleType("homeassistant.components.media_source")
    media_player = types.ModuleType("homeassistant.components.media_player")
    mqtt = types.ModuleType("homeassistant.components.mqtt")
    helpers = types.ModuleType("homeassistant.helpers")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    media_source.is_media_source_id = lambda media_id: str(media_id).startswith(
        "media-source://"
    )
    media_source.async_resolve_media = None
    media_player.MediaPlayerEntity = object
    media_player.MediaPlayerEntityFeature = _MediaPlayerEntityFeature
    media_player.async_process_play_media_url = (
        lambda hass, url: f"processed:{url}"
    )
    mqtt.async_publish = async_publish
    mqtt.async_subscribe = async_subscribe
    mqtt.async_wait_for_mqtt_client = async_wait_for_mqtt_client
    entity_registry.async_get = lambda hass: None
    dt.utcnow = lambda: None

    components.media_source = media_source
    components.media_player = media_player
    components.mqtt = mqtt
    helpers.entity_registry = entity_registry
    util.dt = dt

    package_name = "custom_components.mqtt_media_player"
    package = types.ModuleType(package_name)
    package.__path__ = [
        str(Path(__file__).parents[1] / "custom_components" / "mqtt_media_player")
    ]
    package.entry_device_id = lambda entry: entry.unique_id or entry.data["name"]

    monkeypatch.setitem(sys.modules, "homeassistant", homeassistant)
    monkeypatch.setitem(sys.modules, "homeassistant.components", components)
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.media_source", media_source
    )
    monkeypatch.setitem(
        sys.modules, "homeassistant.components.media_player", media_player
    )
    monkeypatch.setitem(sys.modules, "homeassistant.components.mqtt", mqtt)
    monkeypatch.setitem(sys.modules, "homeassistant.helpers", helpers)
    monkeypatch.setitem(
        sys.modules, "homeassistant.helpers.entity_registry", entity_registry
    )
    monkeypatch.setitem(sys.modules, "homeassistant.util", util)
    monkeypatch.setitem(sys.modules, "homeassistant.util.dt", dt)
    monkeypatch.setitem(sys.modules, package_name, package)
    sys.modules.pop(f"{package_name}.media_player", None)

    return importlib.import_module(f"{package_name}.media_player")


def _player(module):
    config_entry = SimpleNamespace(
        data={"name": "living-room"},
        entry_id="entry-1",
        title="Living Room",
        unique_id="living-room",
    )
    player = module.MQTTMediaPlayer("hass", config_entry, "discovery/topic")
    player.hass = "hass"
    player.entity_id = "media_player.living_room"
    player._cmd_topics["playmedia_topic"] = "living-room/playmedia"
    return player


def test_play_media_resolves_media_source_with_entity_id(monkeypatch):
    module = _load_media_player_module(monkeypatch)
    player = _player(module)
    calls = []

    async def async_resolve_media(hass, media_id, entity_id):
        calls.append((hass, media_id, entity_id))
        return SimpleNamespace(mime_type="audio/mpeg", url="/media/local/song.mp3")

    async def async_publish(hass, topic, payload):
        calls.append((hass, topic, json.loads(payload)))

    monkeypatch.setattr(module.media_source, "async_resolve_media", async_resolve_media)
    monkeypatch.setattr(module, "async_publish", async_publish)

    asyncio.run(
        player.async_play_media("music", "media-source://media_source/local/song.mp3")
    )

    assert calls == [
        (
            "hass",
            "media-source://media_source/local/song.mp3",
            "media_player.living_room",
        ),
        (
            "hass",
            "living-room/playmedia",
            {
                "media_type": "audio/mpeg",
                "media_id": "processed:/media/local/song.mp3",
            },
        ),
    ]


def test_play_media_publishes_plain_url_without_resolving(monkeypatch):
    module = _load_media_player_module(monkeypatch)
    player = _player(module)
    calls = []

    async def async_resolve_media(*args):
        raise AssertionError("plain URLs must not be resolved as media sources")

    async def async_publish(hass, topic, payload):
        calls.append((hass, topic, json.loads(payload)))

    monkeypatch.setattr(module.media_source, "async_resolve_media", async_resolve_media)
    monkeypatch.setattr(module, "async_publish", async_publish)

    asyncio.run(player.async_play_media("music", "https://example.test/song.mp3"))

    assert calls == [
        (
            "hass",
            "living-room/playmedia",
            {
                "media_type": "music",
                "media_id": "https://example.test/song.mp3",
            },
        )
    ]
