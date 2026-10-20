# Accepted API breaking changes

`scripts/ci/api-compat` compares this tree's OpenAPI spec with the last
release's and fails on a change that breaks a client written against that
release, unless the change is listed here. Each entry is the method, path and
message the check printed, under a `## After <release>` heading naming the
release it breaks from. Once the next release ships, its entries no longer
matter and can be deleted.

## After 0.76.0

### New values in a response's enums

- GET /api/v1/notifications/ added the new `community_pause_reminder` enum value to the `notifications/items/type` response property for the response status `200`
- GET /api/v1/notifications/{notification_id}/alert added the new `community_pause_reminder` enum value to the `notification/type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/read added the new `community_pause_reminder` enum value to the `type` response property for the response status `200`
- POST /api/v1/notifications/{notification_id}/unread added the new `community_pause_reminder` enum value to the `type` response property for the response status `200`
- POST /api/v1/auth/register added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `201`
- POST /api/v1/auth/register added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `201`
- GET /api/v1/me added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/me added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/age-confirmation added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/age-confirmation added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PUT /api/v1/me/avatar added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PUT /api/v1/me/avatar added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/legal-acceptance added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/me/legal-acceptance added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me/username added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/me/username added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- GET /api/v1/operator/users added the new `billing.control` enum value to the `items/items/capabilities/items/` response property for the response status `200`
- GET /api/v1/operator/users added the new `billing.directory` enum value to the `items/items/capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/age-block added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/age-block added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/api-keys added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/platform-role added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/profile/{field} added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/reactivate added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/reactivate added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/restore added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/restore added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sessions added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sessions added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- DELETE /api/v1/operator/users/{user_id}/sign-in-lock added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/suspension added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- POST /api/v1/operator/users/{user_id}/suspension added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/username added the new `billing.control` enum value to the `capabilities/items/` response property for the response status `200`
- PATCH /api/v1/operator/users/{user_id}/username added the new `billing.directory` enum value to the `capabilities/items/` response property for the response status `200`

### Groupings name the field they group by

A list layout's groupings name a field of what it lists (`task_status_id`,
`tag_ids`, `date_group`, `assignee_ids`, …) or `property:<id>`, rather than one
of five ids of their own; migration `20261020_0529` rewrites every stored
layout.

- PUT /api/v1/c/{community_id}/layouts/ removed `#/components/schemas/TaskGroupingId` from the `oneOf[subschema #1: ListLayoutWrite]/definition/group_by` request property `anyOf` list
- PUT /api/v1/c/{community_id}/layouts/ removed `#/components/schemas/TaskGroupingId, subschema #2` from the `oneOf[subschema #1: ListLayoutWrite]/definition/groupings/anyOf[subschema #1]/items/field` request property `anyOf` list
- PUT /api/v1/c/{community_id}/layouts/ the `oneOf[subschema #1: ListLayoutWrite]/definition/groupings/anyOf[subschema #1]/items/field` request property `type` changed from `any` to `string`
