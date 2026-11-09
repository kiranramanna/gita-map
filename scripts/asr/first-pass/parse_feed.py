import sys, json
import xml.etree.ElementTree as ET

path, n = sys.argv[1], int(sys.argv[2])
ns = {
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
    "podcast": "https://podcastindex.org/namespace/1.0",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
root = ET.parse(path).getroot()
ch = root.find("channel")
out = {"channel": {
    "title": ch.findtext("title"),
    "link": ch.findtext("link"),
    "author": ch.findtext("itunes:author", namespaces=ns),
    "language": ch.findtext("language"),
    "lastBuildDate": ch.findtext("lastBuildDate"),
    "item_count": len(ch.findall("item")),
    "channel_podcast_tags": sorted({c.tag for c in ch if "podcastindex" in c.tag}),
}, "items": []}
items = ch.findall("item")
tcount = 0
for it in items:
    if it.findall("podcast:transcript", ns):
        tcount += 1
out["channel"]["items_with_podcast_transcript"] = tcount
for it in items[:n]:
    enc = it.find("enclosure")
    out["items"].append({
        "title": it.findtext("title"),
        "guid": it.findtext("guid"),
        "link": it.findtext("link"),
        "pubDate": it.findtext("pubDate"),
        "itunes_duration": it.findtext("itunes:duration", namespaces=ns),
        "itunes_episode": it.findtext("itunes:episode", namespaces=ns),
        "enclosure": dict(enc.attrib) if enc is not None else None,
        "description_verbatim": it.findtext("description"),
        "content_encoded": it.findtext("content:encoded", namespaces=ns),
        "podcast_transcript": [dict(t.attrib) for t in it.findall("podcast:transcript", ns)],
        "podcast_chapters": [dict(t.attrib) for t in it.findall("podcast:chapters", ns)],
        "all_child_tags": [c.tag for c in it],
    })
print(json.dumps(out, indent=1, ensure_ascii=False))
