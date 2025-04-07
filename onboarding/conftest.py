""" conftest.py for onboarding tests """
# pylint: disable=redefined-outer-name, unused-argument

import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient, Client

User = get_user_model()


@sync_to_async
def get_or_create_test_user(username, password):
    """Async helper to get or create a user."""
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


# --- Async-safe Session Helpers ---
@sync_to_async
def set_session_value_sync(client, key, value):
    """Asynchronously sets a value in the session via the client and saves."""
    session = client.session
    session[key] = value
    session.save()


@sync_to_async
def get_session_value_sync(client, key, default=None):
    """Asynchronously gets a value from the session via the client."""
    return client.session.get(key, default)


@sync_to_async
def del_session_key_sync(client, key):
    """Asynchronously deletes a key from the session via the client."""
    session = client.session
    if key in session:
        del session[key]
        session.save()


@sync_to_async
def session_key_exists_sync(client, key):
    """Asynchronously checks if a key exists in the session via the client."""
    return key in client.session


# --- Async-safe Login Helper ---
@sync_to_async
def async_login(client, **credentials):
    """Asynchronously logs in a user using the client."""
    client.login(**credentials)


# --- Fixtures ---
@pytest.fixture
def async_client_fixture():
    """Fixture for creating an async test client."""
    return AsyncClient()


@pytest.fixture
def client_fixture():
    """Fixture for creating a standard test client."""
    return Client()


# Mark the fixture as needing DB access and make it async
@pytest.mark.django_db
@pytest.fixture
async def logged_in_user(async_client_fixture):
    """Fixture to create/get and log in a user asynchronously."""
    user = await get_or_create_test_user(username="testonboard", password="password")
    # Login using the async helper
    await async_login(async_client_fixture, username="testonboard", password="password")
    return user


# Fixture for standard client logged-in user
@pytest.mark.django_db
@pytest.fixture
def logged_in_standard_client(client_fixture):
    """Fixture to create/get a user and return a logged-in standard client."""
    username = "testskipuser"
    password = "password"
    # Use standard ORM calls. Ensure password is set correctly.
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            "email": f"{username}@example.com"
        },  # Don't set raw password in defaults
    )
    user.set_password(password)  # Set/reset password correctly using hashing
    user.save()

    # Login using the standard client passed in
    login_successful = client_fixture.login(username=username, password=password)
    assert login_successful, "Client login failed in fixture"  # Verify login worked

    return client_fixture  # Return the logged-in client