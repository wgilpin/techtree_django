"""URL configuration for the onboarding app."""

from django.urls import path
from . import views

app_name = 'onboarding' # Required for namespacing


# Define URL names for use in templates {% url '...' %}
# We are not using a namespace here, consistent with the 'core' app
urlpatterns = [

    # URL to display the assessment page for a given topic
    # Example: /onboarding/assess/Python%20Programming/
    path('assess/<str:topic>/', views.assessment_page_view, name='onboarding_assessment_page'),

    # URL to start a new assessment for a given topic
    # Example: /onboarding/start/Python%20Programming/
    path('start/<str:topic>/', views.start_assessment_view, name='onboarding_start'),

    # URL to submit an answer during an assessment
    # We might need a way to identify the specific assessment session (e.g., via Django session)
    path('submit/', views.submit_answer_view, name='onboarding_submit'),

    # URL to view the result of a completed assessment (if needed)
    # path('result/', views.assessment_result_view, name='onboarding_result'),

    # URL to handle skipping the assessment
    # pylint: disable=no-member
    path('skip/', views.skip_assessment_view, name='skip_assessment'),
    # URL to initiate syllabus generation after assessment
    path("initiate-syllabus/", views.initiate_syllabus_view, name="initiate_syllabus"),
    # URL to show the 'generating syllabus' loading page
    path("generating/<uuid:syllabus_id>/", views.generating_syllabus_view, name="generating_syllabus"),
    # URL for the frontend to poll syllabus generation status
    path("poll-syllabus-status/<uuid:syllabus_id>/", views.poll_syllabus_status_view, name="poll_syllabus_status"),
]
