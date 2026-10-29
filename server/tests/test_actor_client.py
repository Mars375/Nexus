"""The test client's token cache (#138): a token is only published once its row is committed.

`ActorClient` hands the same actor token to every thread of a test — the two-thread races of
`test_approvals_answer.py` issue it from both threads at once. Publishing the token in `_issued`
before `session.commit()` opens a window where another thread authenticates with a row no other
connection can see yet: the server answers 401 `invalid_token` for a token that is valid, the
request never reaches the race barrier, and the peer thread dies on `BrokenBarrierError`.
"""

from sqlalchemy.orm import Session

from nexus.auth import tokens


def test_a_token_is_published_only_once_its_commit_landed(client, monkeypatch):
    real_commit = Session.commit
    uncommitted = []

    def commit(self):
        # Anything the client can already hand out must be visible to another connection.
        for actor, token in list(client._issued.items()):
            with client.app.state.sessionmaker() as probe:
                if tokens.lookup(probe, token) is None:
                    uncommitted.append(actor)
        return real_commit(self)

    monkeypatch.setattr(Session, "commit", commit)
    client.token_for("loic")

    assert uncommitted == [], "a token was handed out before its row was committed"
