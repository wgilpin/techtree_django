"""Common fixtures for syllabus tests."""

# pylint: disable=no-member, missing-function-docstring, redefined-outer-name

import pytest
from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import AsyncClient, Client

from core.models import Syllabus, Module, Lesson
from core.constants import DIFFICULTY_BEGINNER  # Import constant
from syllabus.services import SyllabusService

User = get_user_model()


# --- Async Helpers ---
async def get_or_create_test_user(username, password):
    """Asynchronously gets or creates a test user."""
    try:
        user = await User.objects.aget(username=username)
        # User exists, ensure password is set (sync operation, needs wrapper)
        set_password_sync = sync_to_async(user.set_password)
        await set_password_sync(password)
        save_user_sync = sync_to_async(user.save)
        await save_user_sync(update_fields=["password"])
    except User.DoesNotExist:
        # User does not exist, create asynchronously
        user = await User.objects.acreate(
            username=username,
            password=password,  # acreate handles hashing
            email=f"{username}@example.com",
        )
    return user


@sync_to_async
def async_client_login(client, **credentials):
    client.login(**credentials)


async def create_syllabus_async(user):
    """Asynchronously creates a test syllabus with modules and lessons."""
    syllabus = await Syllabus.objects.acreate(
        user=user,
        topic="Existing Topic",
        level=DIFFICULTY_BEGINNER,
        user_entered_topic="Existing Topic",
    )
    module1 = await Module.objects.acreate(
        syllabus=syllabus, module_index=0, title="Module 1", summary="Summary 1"
    )
    await Lesson.objects.acreate(
        module=module1,
        lesson_index=0,
        title="Lesson 1.1",
        summary="Summary 1.1",
        duration=10,
    )
    await Lesson.objects.acreate(
        module=module1,
        lesson_index=1,
        title="Lesson 1.2",
        summary="Summary 1.2",
        duration=15,
    )
    module2 = await Module.objects.acreate(
        syllabus=syllabus, module_index=1, title="Module 2", summary="Summary 2"
    )
    await Lesson.objects.acreate(
        module=module2,
        lesson_index=0,
        title="Lesson 2.1",
        summary="Summary 2.1",
        duration=20,
    )
    # Use async prefetch here
    return await Syllabus.objects.prefetch_related("modules__lessons").aget(
        pk=syllabus.pk
    )


# --- Fixtures ---
@pytest.fixture(scope="function")
async def test_user_async():
    """Provides an asynchronously created test user."""
    # Note: Password needs to be set correctly for login/force_login later
    return await get_or_create_test_user(username="testuser_async", password="password")


@pytest.fixture(scope="function")
def test_user_sync():
    user, created = User.objects.get_or_create(username="testsyllabususer_sync")
    if created:
        user.set_password("password")
        user.save()
    return user


@pytest.fixture
def syllabus_service():
    return SyllabusService()


@pytest.fixture
async def existing_syllabus_async(test_user_sync):  # Use the SYNC user fixture
    """Provides an asynchronously created syllabus linked to a sync user."""
    # Pass the sync user to the async creator helper
    return await create_syllabus_async(test_user_sync)


# Synchronous version of the syllabus fixture
@pytest.fixture
def existing_syllabus_sync(test_user_sync):
    """Provides a synchronously created syllabus linked to a sync user."""
    syllabus = Syllabus.objects.create(
        user=test_user_sync,
        topic="Existing Sync Topic",
        level=DIFFICULTY_BEGINNER,
        user_entered_topic="Existing Sync Topic",
    )
    module1 = Module.objects.create(
        syllabus=syllabus, module_index=0, title="Sync Module 1", summary="Summary 1"
    )
    Lesson.objects.create(
        module=module1,
        lesson_index=0,
        title="Sync Lesson 1.1",
        summary="Summary 1.1",
        duration=10,
    )
    Lesson.objects.create(
        module=module1,
        lesson_index=1,
        title="Sync Lesson 1.2",
        summary="Summary 1.2",
        duration=15,
    )
    module2 = Module.objects.create(
        syllabus=syllabus, module_index=1, title="Sync Module 2", summary="Summary 2"
    )
    Lesson.objects.create(
        module=module2,
        lesson_index=0,
        title="Sync Lesson 2.1",
        summary="Summary 2.1",
        duration=20,
    )
    # Return the prefetched object
    return Syllabus.objects.prefetch_related("modules__lessons").get(pk=syllabus.pk)


@pytest.fixture
def async_client():
    return AsyncClient()


@pytest.fixture
def client():
    return Client()


@pytest.fixture
async def logged_in_async_client(async_client, test_user_sync):  # Use sync user fixture
    """Logs in a user for the AsyncClient by setting the session cookie manually."""
    user = test_user_sync  # Get the sync user
    sync_client = Client()  # Use standard sync client to login and get cookie

    # Perform login synchronously
    sync_client.login(username=user.username, password="password")

    # Get session cookie from sync client and set it on async client
    cookie = sync_client.cookies.get(settings.SESSION_COOKIE_NAME)
    if cookie:
        async_client.cookies[settings.SESSION_COOKIE_NAME] = cookie.value

    return async_client


@pytest.fixture
def logged_in_client(client, test_user_sync):
    client.login(username=test_user_sync.username, password="password")
    return client
