# AILang Language Reference

> A token-efficient systems language that compiles to C++.
> Designed for AI code generation — every syntax decision minimizes tokens spent.

---

## Table of Contents

1. [Core Philosophy](#core-philosophy)
2. [Reserved Keywords](#reserved-keywords)
3. [Imports](#imports)
4. [Variables](#variables)
5. [Functions](#functions)
6. [Classes](#classes)
7. [Enums](#enums)
8. [Control Flow](#control-flow)
9. [Match](#match)
10. [Error Handling](#error-handling)
11. [Expressions](#expressions)
12. [Types](#types)
13. [Collections](#collections)
14. [Literals & String Interpolation](#literals--string-interpolation)
15. [Lambdas](#lambdas)
16. [Parser Notes & Ambiguities](#parser-notes--ambiguities)

---

## Core Philosophy

- **Immutable by default** — safer code without extra keywords
- **Type inference everywhere** — annotate only when needed
- **Short keywords** — `cls`, `exp`, `chr`, `str` over verbose alternatives
- **Python-style indentation** — no braces, blocks via INDENT/DEDENT
- **Implicit return** — last expression in a function body is the return value
- **`?` propagation** — errors bubble up without boilerplate
- **Flat imports** — no repeated namespace prefixes at callsite

---

## Reserved Keywords

```
use   as    exp   cls   enum
if    elif  else
loop  for   in    match
return break continue
throw try   catch
async await
true  false
self  super
Map   Set   Deque  PQueue
```

**Removed intentionally** (not in language):
`macro`, `template`, `typedef`, `union`, `constexpr`, `volatile`,
`goto`, `switch`, `case`, `default`, `new`, `delete`,
`stack`, `queue` (covered by `[T]` and `Deque[T]`)

---

## Imports

Three forms — pick the shortest one that fits the situation.

### Forms

```
use std.math              # access as math.sqrt()
use std.math as m         # access as m.sqrt()
use std.math as *         # access as sqrt() directly
```

### Selective Import

Import a single item flat — most token-efficient when you need only one thing:

```
use std.math.sqrt as *    # only sqrt imported, call as sqrt()
use std.math.PI as *      # only PI imported, call as PI
```

### When to Use Each Form

| Form | Use when |
|------|----------|
| `use lib as *` | Need many things from lib, no name conflicts |
| `use lib.func as *` | Need only one or two specific items |
| `use lib as m` | Short alias when conflicts exist |
| `use lib` | Explicit prefix preferred for clarity |

### Collision Handling

Name collisions between libraries are resolved automatically by C++ overloading — **same name with different argument types is not a conflict:**

```
use std.io as *
use graphics.io as *

print(42)          # int version   → resolves to std.io.print
print(mySprite)    # Sprite version → resolves to graphics.io.print
```

**Only identical signatures cause a true conflict** — same name, same argument types from two different libraries. In that case use alias form:

```
use std.io as sio
use mylib.io as mio

sio.print("hello")
mio.print("hello")
```

### Token Cost at Callsite

| Import form | Callsite | Tokens |
|-------------|----------|--------|
| `use std.math` | `math.sqrt(9)` | 3 |
| `use std.math as m` | `m.sqrt(9)` | 3 |
| `use std.math as *` | `sqrt(9)` | 2 |
| `use std.math.sqrt as *` | `sqrt(9)` | 2 |

---

## Variables

### Mutability

| Syntax | Meaning |
|--------|---------|
| `x = value` | immutable (default) |
| `x := value` | mutable |

### Single Declaration

```
x = 42                  # immutable, inferred as int
y := 3.14               # mutable, inferred as f64
name:str = "Alice"      # immutable, explicit type
count:int := 0          # mutable, explicit type
```

### Multi-Variable Declaration

```
x, y, z := 1, 2, 3
a:int, b:str = 10, "hello"
first, _, last = tuple        # _ discards middle value
```

- All targets share the same `:=` or `=` mutability
- Count of targets must match count of values
- `_` is the discard identifier — value evaluated but not bound

### Export

```
exp PI = 3.14159
exp version:str = "1.0.0"
```

### Assignment Operators

```
x = 5
x += 1 | x -= 1 | x *= 2 | x /= 2 | x %= 3
```

---

## Functions

### Forms

```
# Multi-line body
add(a:int, b:int) -> int:
    a + b               # implicit return

# Single-expression
square(x:int) -> int => x * x

# Single-line body
greet(name:str): print("hello {name}")
```

### Export & Async

```
exp add(a:int, b:int) -> int => a + b

async fetchData(url:str) -> str:
    result = await httpGet(url)
    result.body
```

### Parameters

- Every parameter needs a type: `name:type`
- `_:type` to discard a parameter
- `self` is **auto-injected** in class methods — never declare it explicitly

### Return

- **Implicit** — last expression in block is returned automatically
- **Explicit** — use `return` for early exit

```
clamp(x:int, lo:int, hi:int) -> int:
    if x < lo: return lo
    if x > hi: return hi
    x
```

---

## Classes

```
cls Point:
    x:f64 = 0.0
    y:f64 = 0.0

    dist(other:Point) -> f64:
        dx = self.x - other.x
        dy = self.y - other.y
        sqrt(dx*dx + dy*dy)
```

### Generics

```
cls Stack[T]:
    data:[T] := []

    push(val:T):
        self.data.append(val)

    pop() -> T?:
        self.data.pop()?
```

### Notes

- `self` always available inside methods — auto-injected, never declared
- `super` refers to the parent class
- Fields declared at top of class body using `var_decl` syntax
- `exp cls Name:` exports the class

---

## Enums

```
enum Direction:
    North
    South
    East
    West

enum Shape:
    Circle(f64)             # radius
    Rect(f64, f64)          # width, height
    Triangle(f64, f64, f64)
```

- Variants without payload are simple constants
- Variants with payload use tuple-style types
- Export: `exp enum Color:`

---

## Control Flow

### If / Elif / Else

```
if x > 0: print("positive")          # single-line

if x > 0:
    print("positive")
elif x < 0:
    print("negative")
else:
    print("zero")
```

### Loop

```
loop:                    # infinite
    if done: break

loop x < 100:            # while
    x *= 2

loop running: tick()     # single-line while
```

### For — Range

```
for i in 0..10:          # 0 to 9
    print(i)

for i in 0..100, 5:      # step 5: 0,5,10,...
    print(i)

for i in 1..n:           # variable bound, valid
    process(i)

for _ in 0..10:          # discard index
    doRepeat()
```

### For — Each

Works on any iterable: `[T]`, `[T,N]`, `Set[T]`, `Deque[T]`, tuples.

```
for item in arr:
    print(item)

for x in mySet:
    process(x)
```

### For — Map

```
for name, score in scores:
    print("{name}: {score}")

for _, score in scores:      # discard key
    total += score

for name, _ in scores:       # discard value
    names.add(name)
```

### Break / Continue

```
for i in 0..100:
    if i % 2 == 0: continue
    if i > 50: break
    print(i)
```

---

## Match

Match works like switch. Arms checked top to bottom. `EOF` is the default arm and **must be last**.

```
match status:
    200: print("ok")
    404: print("not found")
    500: print("server error")
    EOF: print("unknown")
```

### Multiple Patterns Per Arm

```
match day:
    1 | 7: print("weekend")
    2 | 3 | 4 | 5 | 6: print("weekday")
    EOF: print("invalid")
```

### Enum Destructuring

```
match shape:
    Circle(r):   area = PI * r * r
    Rect(w, h):  area = w * h
    EOF:         area = 0.0
```

### Wildcard in Destructuring

```
match event:
    Click(x, _): handleX(x)
    EOF: ignore()
```

### Multi-Line Arms

```
match command:
    "quit":
        saveState()
        exit(0)
    EOF:
        print("unknown command")
```

---

## Error Handling

### Propagation with `?`

```
readFile(path:str) -> str:
    f = open(path)?
    f.read()?
```

### Throw

```
throw ValueError("x must be positive")
```

### Try / Catch — Three Forms

```
# typed, no name — most token-efficient
try:
    riskyCall()
catch NetworkError:
    retry()

# named + typed — when you need the error value
try:
    riskyCall()
catch e:NetworkError:
    log(e.message)

# catch-all
try:
    riskyCall()
catch:
    log("something failed")
```

### Multiple Catch Clauses

```
try:
    connect(host)
catch TimeoutError:   retryLater()
catch AuthError:      refreshToken()
catch e:NetworkError: log("network: {e.message}")
catch:                log("unknown")
```

---

## Expressions

### Operator Precedence (low to high)

| Level | Operators |
|-------|-----------|
| Assignment | `=` `+=` `-=` `*=` `/=` `%=` |
| Logical OR | `\|\|` |
| Logical AND | `&&` |
| Bitwise OR | `\|` |
| Bitwise XOR | `^` |
| Bitwise AND | `&` |
| Equality | `==` `!=` |
| Comparison | `<` `>` `<=` `>=` (chainable) |
| Shift | `<<` `>>` |
| Term | `+` `-` |
| Factor | `*` `/` `%` |
| Unary | `-` `!` `~` `await` |
| Postfix | `.field` `(call)` `[index]` `?` |

### Chained Comparisons

```
0 < x < 10
a <= b <= c
```

### Await + Propagate

```
data = await fetchJson(url)
result = await db.query(sql)?
```

---

## Types

### Primitive Types

| Type | C++ | Notes |
|------|-----|-------|
| `i8` `i16` `int` `i64` | `int8_t` `int16_t` `int32_t` `int64_t` | `int` = i32 |
| `u8` `u16` `u32` `u64` | `uint8_t` … | Unsigned |
| `f32` `f64` | `float` `double` | |
| `chr` | `char` | Single character |
| `str` | `std::string` | |

### Nullable Types

```
x:int? = null
name:str? = getName()
```

---

## Collections

### Full Reference

| AILang type | C++ equivalent | Notes |
|-------------|---------------|-------|
| `[T]` | `vector<T>` | dynamic, empty |
| `[T, N]` | `array<T,N>` | static, N = integer literal |
| `[T, var]` | `vector<T>(var)` | dynamic, pre-sized |
| `{K:V}` | `unordered_map<K,V>` | hash map |
| `Map[K,V]` | `map<K,V>` | ordered map, sorted keys |
| `Set[T]` | `unordered_set<T>` | unique values, hash lookup |
| `Deque[T]` | `deque<T>` | double-ended, covers queue+stack |
| `PQueue[T]` | `priority_queue<T,vector<T>,greater<T>>` | **min-heap** default |
| `(T, U)` | `tuple<T,U>` / `pair<T,U>` | fixed heterogeneous |
| `T?` | `optional<T>` | nullable any type |

### Array Type Rules

```
buf:[int,256]        # array<int,256>  — static,  N is literal
buf:[int,n]          # vector<int>(n)  — dynamic, N is variable
buf:[int]            # vector<int>     — dynamic, empty
```

- **Integer literal** after comma → `std::array` (stack allocated, fixed)
- **Identifier** after comma → `std::vector` pre-sized to that variable
- **Nothing** after comma → empty `std::vector`

### Why No Stack / Queue Types?

```
# Stack — use [T]
s:[int] := []
s.push(x)            # push_back
s.pop()              # pop_back
top = s.top()        # back()

# Queue — use Deque[T]
q:Deque[int] := Deque[int]()
q.pushBack(x)
front = q.popFront()
```

### Sized Vector Literals

```
buf   = 256*[0]        # vector<int>(256, 0)
flags = n*[false]      # vector<bool>(n, false)
mat   = rows*[0.0]     # vector<f64>(rows, 0.0)
raw   = n*[]           # vector<T>(n), type from context
```

**Rules:**
- Left of `*` — any expression (literal or identifier)
- Inside `[]` — at most **one** simple value: literal or single identifier. No sub-expressions
- `n*[x+1]` is **invalid**
- Result is always a dynamic `vector`, never a static `array`

### Collection Examples

```
# dynamic vector
nums:[int] := []
nums = 10*[0]

# static array
buf:[int,256]

# sized dynamic vector
buf:[int,n]

# unordered map
ages = {"Alice":30, "Bob":25}

# ordered map
scores:Map[str,int] := Map[str,int]()

# set
seen:Set[int] := Set[int]()
seen.add(x)
if seen.has(x): ...

# deque as queue
q:Deque[int] := Deque[int]()
q.pushBack(1)
front = q.popFront()

# deque as stack
q.pushFront(1)
top = q.popFront()

# min-heap priority queue
pq:PQueue[int] := PQueue[int]()
pq.push(5)
smallest = pq.top()
pq.pop()

# tuple destructure
coord:(int,int) = (10, 20)
x, y = coord
```

---

## Literals & String Interpolation

### String Interpolation

```
name = "Alice"
age  = 30

"Hello {name}!"
"Name: {name}, Age: {age}"
"2 + 2 = {2 + 2}"
"Upper: {name.toUpper()}"
```

- Any valid expression inside `{}`
- Escape literal brace with `\{`

### Other Literals

```
42            # integer
3.14          # float
'a'           # char
true  false   # boolean

[1, 2, 3]           # array  → vector
(1, "hello")        # tuple
{"a":1, "b":2}      # map    → unordered_map
[]                  # empty vector (type from context)
{}                  # empty map    (type from context)
```

---

## Lambdas

```
double  = (x) => x * 2
add     = (a, b) => a + b
greet   = () => "hello"
ignored = (_) => 42

# Inline
doubled = nums.map((x) => x * 2)
evens   = nums.filter((x) => x % 2 == 0)
```

- Params are **untyped** — inferred from context
- Use `_` to discard a param

---

## Parser Notes & Ambiguities

### Import Disambiguation

`use lib` vs `use lib as id` vs `use lib as *` — all three are unambiguous since `as` is a reserved keyword and `*` is not a valid identifier.

### `for_each` vs `for_range` Disambiguation

Both start with `for identifier in`. Parser uses `..` as lookahead after the first expression:
- `..` present → `for_range_stmt`
- `:` directly → `for_each_stmt`
- `identifier , identifier in` → `for_map_stmt`

### Static Array vs Sized Vector vs Empty Vector

Resolved from the type annotation:
- `[T, N]` where N is an **integer literal** → `std::array<T,N>`
- `[T, v]` where v is an **identifier** → `std::vector<T>(v)`
- `[T]` → `std::vector<T>` empty

`n*[val]` in an expression always produces a `vector` regardless of whether n is a literal.

### `sized_vector_literal` vs `factor` Disambiguation

`n*[val]` could parse as `n * array_literal`. Parser resolves by checking what follows `*`:
- `[` with at most one simple token and no `,` inside → `sized_vector_literal`
- `[` with a list or complex expression → normal `factor` with array

### `catch` Disambiguation

After `catch`:
- `:` immediately → catch-all
- `identifier : type :` → named + typed
- `identifier :` then block/statement → typed-only (identifier is the type name)

### Tuple vs Grouped Expression

`(expr)` → grouped. `(expr, expr_list)` → tuple. The `,` is the distinguishing token.

### Lambda vs Grouped Expression

`(params) =>` → lambda. `(expr)` alone → grouped. `=>` after `)` is the lookahead.

### Map Type vs Map Literal

`{K:V}` in a **type position** → `unordered_map<K,V>`.
`{expr:expr}` in an **expression position** → map literal.
Context (after `:` in a declaration vs inside an expression) determines which rule applies.

### `self` Injection

`self` is automatically available in all `cls` methods. Never appears in `param_list`. Compiler injects it as first parameter. Access fields via `self.fieldName`.
