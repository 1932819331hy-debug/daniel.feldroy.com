"""Dependency-free checks of writing_stats' emitted component arguments.

Run with: python -m unittest discover -s tests -v
This extracts the actual route body without importing/starting the whole site.
Air/Layout constructors record arguments only: these are not HTML rendering,
network/CDN loading, browser JavaScript or full-application integration tests.
"""

import ast
import collections
import copy
import json
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from urllib.parse import urlsplit


def component(name):
    def record(*children, **attributes):
        return (name, children, attributes)

    return record


def route_output(posts):
    source = Path(__file__).resolve().parents[1] / "main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    routes = [
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "writing_stats"
    ]
    if len(routes) != 1:
        raise AssertionError("expected one writing_stats route")
    route = routes[0]
    # Only app registration is omitted; every statement/expression stays real.
    route.decorator_list = []
    module = ast.Module(body=[route], type_ignores=[])
    namespace = {
        "collections": collections,
        "json": json,
        "list_posts": lambda: posts,
        "Layout": component("Layout"),
        "air": SimpleNamespace(**{
            name: component(name) for name in ("Title", "Script", "Div", "Children")
        }),
    }
    exec(compile(module, str(source), "exec"), namespace)
    coroutine = namespace["writing_stats"]()
    try:
        # This route has no await/I/O. No event loop or socket is needed.
        coroutine.send(None)
    except StopIteration as result:
        return result.value
    else:
        raise AssertionError("route unexpectedly suspended")
    finally:
        coroutine.close()


def flatten(node):
    yield node
    for child in node[1]:
        if isinstance(child, tuple):
            yield from flatten(child)


def initializer_arguments(nodes):
    scripts = [node for node in nodes if node[0] == "Script" and not node[2]]
    if len(scripts) != 1 or len(scripts[0][1]) != 1:
        raise AssertionError("expected one inline chart initializer")
    match = re.fullmatch(
        r"Plotly\.newPlot\('([^']+)', (\[.*\]), (\{.*\}), (\{.*\})\);",
        scripts[0][1][0],
    )
    if match is None:
        raise AssertionError("unexpected chart initializer")
    target, data, layout, config = match.groups()
    return target, ast.literal_eval(data), json.loads(layout), json.loads(config)


class WritingStatsTests(unittest.TestCase):
    def test_plotly_dependency_has_a_supported_secure_url(self):
        nodes = list(flatten(route_output([])))
        scripts = [node for node in nodes if node[0] == "Script" and "src" in node[2]]
        self.assertEqual(len(scripts), 1)
        url = urlsplit(scripts[0][2]["src"])
        self.assertEqual(url.scheme, "https")
        self.assertEqual(url.netloc, "cdn.plot.ly")
        self.assertEqual(url.path, "/plotly-4.0.0.min.js")
        self.assertEqual((url.query, url.fragment), ("", ""))

    def test_dependency_precedes_chart_initialization(self):
        nodes = list(flatten(route_output([])))
        scripts = [node for node in nodes if node[0] == "Script"]
        self.assertEqual(len(scripts), 2)
        self.assertIn("src", scripts[0][2])
        self.assertEqual(set(scripts[0][2]), {"src"})  # no async/defer race
        self.assertTrue(scripts[1][1][0].startswith("Plotly.newPlot("))
        target, _, _, _ = initializer_arguments(nodes)
        containers = [node for node in nodes if node[0] == "Div"]
        self.assertEqual([node[2].get("id") for node in containers], [target])
        self.assertLess(nodes.index(containers[0]), nodes.index(scripts[1]))

    def test_real_route_groups_posts_and_preserves_chart_options(self):
        posts = [{"attributes": {"date": date}} for date in (
            "2023-03-02", "2025-01-02", "2023-04-05",
        )]
        before = copy.deepcopy(posts)
        target, data, layout, config = initializer_arguments(list(flatten(route_output(posts))))
        self.assertEqual(target, "post-counts")
        self.assertEqual(data, [{"x": [2023, 2025], "y": [2, 1], "type": "scatter"}])
        self.assertEqual(layout, {
            "title": {"text": "Writing stats"}, "font": {"size": 18}, "barcornerradius": 15,
        })
        self.assertEqual(config, {"responsive": True})
        self.assertEqual(posts, before)

    def test_empty_posts_still_initialize_an_empty_chart(self):
        _, data, _, config = initializer_arguments(list(flatten(route_output([]))))
        self.assertEqual(data, [{"x": [], "y": [], "type": "scatter"}])
        self.assertEqual(config, {"responsive": True})


if __name__ == "__main__":
    unittest.main()
