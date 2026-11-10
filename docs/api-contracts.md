# API contract evidence

The source is the public My Boat web client. "Live" means a read through this CLI against a real account; it does not establish write behavior. Synthetic tests exercise an independent local HTTP service, not Skippo. The service is undocumented and can change.

| Operation | Source contract | Synthetic E2E | Live |
| --- | --- | --- | --- |
| Login | Firebase Identity Toolkit signInWithPassword | yes | yes |
| Refresh | Firebase Secure Token | yes | no |
| Boats list/show | GET /boat-profiles, boatProfiles | yes | yes |
| Home harbor | POST /boat-profiles/{id}/home-harbor, `{lat,lon}` | yes | yes, isolated temporary boat |
| Boat update | POST /boat-profiles/{id}/base-data, preserving baseData | yes | yes, isolated temporary boat |
| Engines list | profile `engines` (live) or `engine` (web source) | yes | yes, empty and populated |
| Engine add/update | POST /boat-profiles/{id}/engine, `{type,data}` | yes | yes, isolated temporary boat |
| Checklists list/show | profile `checklists` | yes | yes |
| Check/uncheck | PUT /checklists/item/{id}?checked={boolean} | yes | no |
| Events list/show | GET /boat-profiles/{id}/boat-events/all | yes | yes, empty and populated on temporary boat |
| Events add | POST /boat-profiles/{id}/boat-events | yes | yes, isolated temporary boat |
| Notes list/show | GET /boat-profiles/{id}/notes/all | yes | yes, empty and populated on temporary boat |
| Notes add/update | POST /boat-profiles/{id}/notes/note | yes | yes, isolated temporary boat |
| Notes delete | DELETE /boat-profiles/{id}/notes/note/{id} | yes | yes, isolated temporary boat |
| Trips | Firestore `users/{uid}/tracks2026`, derived from Android repository | yes | account received PERMISSION_DENIED; contents unverified |

Event dates use UTC midnight for creation and inclusive UTC calendar dates for local filtering. Event collection is retrieved in full before applying the result limit. The web source does not demonstrate paging. Engine types are diesel=0, petrol=1, electric=2, other=3, none=4. Event categories are purchase=0, installation=1, repair=2, service=3, fuel=4, other=5. Identifiers are verified against the selected boat before changes. No account data are cached.

The service dropped `numberOfEngines` from a live write response; the CLI blocks that field. The temporary boat had no mutable checklist item, so checklist writes remain unverified live. The temporary boat was deleted and its absence verified. Trips scan up to 1,000 documents in ten pages before local UTC date filtering, and reject a repeated cursor. The limit controls returned results separately from the scan bound. Trip details do not include route points.
