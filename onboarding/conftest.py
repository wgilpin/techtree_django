"""conftest.py for onboarding tests"""

# pylint: disable=redefined-outer-name, unused-argument

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


def get_or_create_test_user(username, password):
    """Helper to get or create a user ."""
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "password": password,  # Note: In real tests, use set_password
            "email": f"{username}@example.com",
        },
    )
    if not created:
        user.set_password(password)
        user.save()
    return user


def set_session_value(client, key, value):
    """Sets a value in the session via the client and saves."""
    session = client.session
    session[key] = value
    session.save()


def get_session_value(client, key, default=None):
    """Gets a value from the session via the client."""
    return client.session.get(key, default)


def del_session_key(client, key):
    """Deletes a key from the session via the client."""
    session = client.session
    if key in session:
        del session[key]
        session.save()


def session_key_exists(client, key):
    """Checks if a key exists in the session via the client."""
    return key in client.session


@pytest.fixture
def client_fixture():
    """Fixture for creating a standard test client."""
    return Client()


@pytest.mark.django_db
@pytest.fixture
def logged_in_standard_client(client_fixture):
    """Fixture to create/get a user and return a logged-in standard client."""
    username = "testskipuser"
    password = "password"
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    user.set_password(password)
    user.save()

    login_successful = client_fixture.login(username=username, password=password)
    assert login_successful, "Client login failed in fixture"

    return client_fixture
