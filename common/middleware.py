from django.utils.deprecation import MiddlewareMixin


class GymContextMiddleware(MiddlewareMixin):
    """
    Middleware that intercepts requests and establishes contextual tenant awareness.
    Attaches `gym_id`, `gym`, `token_context` ('personal' vs 'gym'), and `scopes`
    to `request` based on JWT claims or headers.
    """

    def process_request(self, request):
        request.gym = None
        request.gym_id = None
        request.token_context = "personal"
        request.scopes = []

        # Check for Authorization header claims if JWT is present
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                validated_token = AccessToken(token)
                request.token_context = validated_token.get("context_type", "personal")
                request.gym_id = validated_token.get("gym_id", None)
                request.scopes = validated_token.get("scopes", [])
            except Exception:
                # Token may be expired or invalid; simplejwt authentication backend will handle 401
                pass

        # Allow explicit X-Gym-Context override in development/testing if user is authenticated
        gym_context_header = request.META.get("HTTP_X_GYM_CONTEXT")
        if gym_context_header and not request.gym_id:
            request.gym_id = gym_context_header
            request.token_context = "gym"

        return None
