import json

from django.urls import reverse


def test_login_page_has_no_wcag_a_or_aa_violations(page, live_server):
    response = page.goto(
        f"{live_server.url}{reverse('login')}", wait_until="domcontentloaded"
    )
    assert response is not None and response.status == 200

    page.add_script_tag(path="/opt/axe.min.js")
    violations = page.evaluate(
        """async () => {
            const result = await axe.run(document, {
                runOnly: {
                    type: 'tag',
                    values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'],
                },
            });
            return result.violations.map(({ id, impact, description, nodes }) => ({
                id,
                impact,
                description,
                affectedElements: nodes.length,
            }));
        }"""
    )

    assert not violations, json.dumps(violations, ensure_ascii=False, indent=2)
