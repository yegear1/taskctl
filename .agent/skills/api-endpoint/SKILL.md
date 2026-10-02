---
name: api-endpoint
description: Canonical procedure for implementing and evolving HTTP/REST endpoints with strict typing, layered architecture (Router -> Service -> Repository), and contract validation.
---

# REST Endpoint Development (`api-endpoint`)

## 1. Context and Objective
This skill standardizes the creation and evolution of HTTP/REST endpoints, ensuring **end-to-end strict typing**, **decoupled layered architecture**, and **predictable data contracts** for web, mobile, and inter-service clients.

---

## 2. When to Use (Triggers)
Activate this skill whenever the task involves:
- Creating a new HTTP route (e.g., `POST /orders`, `GET /users/{id}`).
- Adding parameters, query arguments, or request bodies to existing endpoints.
- Refactoring routes to improve decoupling or performance.
- Adding error handling or standardizing HTTP response codes.

---

## 3. Associated Tools and MCP Servers
- **MCP Servers:** API documentation servers or database MCPs to inspect existing schemas (strictly read-only).
- **Testing & CLI Tools:** HTTP test runners (e.g. `pytest` with `httpx`/`TestClient`, `vitest`/`jest` with `supertest`, `go test`).

---

## 4. Step-by-Step Operational Procedure

### Step 1: Contract Definition (Schemas First)
Before writing route handlers, explicitly define strict validation schemas:
1. **Request Schema:** Mandatory typing for Request Body, Query Parameters, and Path Parameters (e.g., Pydantic, Zod, typed structs).
2. **Response Schema:** Typed payloads for success statuses (200/201) and standardized error formats (400/404/422/500).
3. Disallow unknown/unvalidated fields.

### Step 2: Strict Layer Separation
Implementation MUST follow 3 isolated layers:

1. **Controller / Router (Thin Web Layer):**
   - Extracts parameters and validates payloads against the schema.
   - Invokes the use case / service layer.
   - Returns appropriate HTTP status codes (`201` for creation, `200` for reads/updates with body, `204` for success without body).
   - ⚠️ **FORBIDDEN:** Executing raw SQL, calling ORM methods directly, or handling business logic in controllers.
2. **Service / Use Case (Pure Business Logic):**
   - Orchestrates domain rules (computations, validations, domain event publishing).
   - Independent of HTTP framework objects (no `Request`, `Response`, or `Headers` parameters).
   - Throws typed domain exceptions (e.g., `EntityNotFoundException`, `InsufficientFundsException`).
3. **Repository / Gateway (Data Access):**
   - Encapsulates database queries or external API calls.

### Step 3: Standardized Error Handling
- Domain exceptions must be caught by a global middleware/exception handler and mapped to HTTP status codes:
  - `EntityNotFoundException` ➔ `404 Not Found`
  - `ValidationException` / Invalid Schema ➔ `422 Unprocessable Entity` or `400 Bad Request`
  - `UnauthorizedException` ➔ `401 Unauthorized`
  - `ForbiddenException` ➔ `403 Forbidden`
  - `ConflictException` ➔ `409 Conflict`
- Never leak raw stack traces, database queries, or server internals to external clients.

### Step 4: Automated Integration Tests
For every new or updated endpoint, write automated tests covering:
1. **Happy Path:** Valid request returns expected status (`200 OK` or `201 Created`) with the matching payload schema.
2. **Validation Failure:** Invalid request payload returns `400` or `422` with actionable error messages.
3. **Edge Cases:** Resource not found (`404`) or uniqueness conflicts (`409`).

### Step 5: Document in Governance
Record the endpoint in the **Active Contracts** table in `.agent/NOTES.md` with route, method, and schema references.

---

## 5. Code Standards and Canonical Example

```typescript
// Canonical layer separation example in TypeScript / Zod

// 1. SCHEMAS (Strict Contract)
export const CreateUserRequestSchema = z.object({
  name: z.string().min(2).max(100),
  email: z.string().email(),
});
export type CreateUserRequest = z.infer<typeof CreateUserRequestSchema>;

export const UserResponseSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  email: z.string().email(),
  createdAt: z.string().datetime(),
});
export type UserResponse = z.infer<typeof UserResponseSchema>;

// 2. CONTROLLER (Thin - No business logic)
export async function createUserController(req: Request, res: Response) {
  // Strict payload validation
  const validatedPayload = CreateUserRequestSchema.parse(req.body);
  
  // Delegate to service layer
  const createdUser = await userService.createUser(validatedPayload);
  
  return res.status(201).json(createdUser);
}

// 3. SERVICE (Pure Business Logic)
export class UserService {
  constructor(private userRepository: UserRepository) {}

  async createUser(data: CreateUserRequest): Promise<UserResponse> {
    const existing = await this.userRepository.findByEmail(data.email);
    if (existing) {
      throw new EmailAlreadyInUseError(data.email);
    }
    return this.userRepository.save(data);
  }
}
```

---

## 6. Known Gotchas and Anti-Patterns
- ⚠️ **DO NOT:** Return `200 OK` containing `{ status: "error", message: "..." }`. Use semantic HTTP status codes.
- ⚠️ **DO NOT:** Write database queries (`SELECT ...`) inside controllers or router files.
- ⚠️ **DO NOT:** Use loose types (`any`, `Object`, unvalidated maps) for endpoint inputs or outputs.
- 💡 **DO:** Validate path parameters (`/users/:id`), query params (`?page=1`), and request bodies against strict schemas.
- 💡 **DO:** Catch infrastructure exceptions so internal credentials, paths, or SQL statements never leak in HTTP responses.

---

## 7. Skill Completion Checklist
- [ ] Request and Response schemas defined with strict typing (no `any`).
- [ ] Controller free of business logic and direct database access.
- [ ] Service layer decoupled from HTTP framework specifics.
- [ ] Semantic HTTP status codes applied.
- [ ] Automated integration tests pass for both success and error scenarios.
- [ ] Contract documented in `.agent/NOTES.md`.
