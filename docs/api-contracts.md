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
| Check/uncheck | PUT /checklists/item/{id}?checked={boolean} | yes | yes, isolated temporary item |
| Checklist item add/delete | POST /checklists/{id}/item?text=...; DELETE /checklists/item/{id} | yes | yes, isolated temporary item |
| Fuel list/show/add/update/delete | Event category 4; POST and DELETE boat-events endpoints | yes | add/read on temporary boat |
| Attachments list/upload/download/delete | Event `assets`; POST /web/assets/add, DELETE /web/assets/delete/{id}; original CDN URL | yes | PNG upload/download/delete; PDF original bytes verified on temporary event |
| Navigation settings | profile `navigationSettings`; POST /boat-profiles/{id}/navigation-settings | yes | write/read on temporary boat; speed rounded to 2 decimals |
| Insurance | profile `insurance`; GET /insurances/companies/list; POST /boat-profiles/{id}/boat-insurance; DELETE /boat-profiles/{id}/boat-insurance/insurance/{id} | yes | update/delete temporary boat |
| Events list/show | GET /boat-profiles/{id}/boat-events/all | yes | yes, empty and populated on temporary boat |
| Events add | POST /boat-profiles/{id}/boat-events | yes | yes, isolated temporary boat |
| Notes list/show | GET /boat-profiles/{id}/notes/all | yes | yes, empty and populated on temporary boat |
| Notes add/update | POST /boat-profiles/{id}/notes/note | yes | yes, isolated temporary boat |
| Notes delete | DELETE /boat-profiles/{id}/notes/note/{id} | yes | yes, isolated temporary boat |
| Trips | Firestore `users/{uid}/tracks2026`, derived from Android repository | yes | account received PERMISSION_DENIED; contents unverified |

Event dates use UTC midnight for creation and inclusive UTC calendar dates for local filtering. Event collection is retrieved in full before applying the result limit. The web source does not demonstrate paging. Engine types are diesel=0, petrol=1, electric=2, other=3, none=4. Event categories are purchase=0, installation=1, repair=2, service=3, fuel=4, other=5. Identifiers are verified against the selected boat before changes. No account data are cached.

The service dropped `numberOfEngines` from a live write response; the CLI blocks that field. A user-created checklist item was added, checked, unchecked and deleted on a temporary boat. The temporary boat was deleted and its absence verified. Trips scan up to 1,000 documents in ten pages before local UTC date filtering, and reject a repeated cursor. The limit controls returned results separately from the scan bound. Trip details do not include route points.

The fuel quick-entry client stores litres as the event description and does not define tank level or a separately persisted unit price. The web client supports adding and deleting user-created checklist items but does not establish whole-list creation, item rename, or reordering. Built-in checklist completion may be inferred by the client from safety and insurance fields; the CLI returns raw service values. Attachments use the source `IMAGE` upload type for all files; the backend also accepted PDF and returned original bytes, but the app picker and preview do not establish native PDF support. CDN downloads use no account headers.
