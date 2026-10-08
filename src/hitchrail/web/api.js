/* -- talking to the API ------------------------------------------------
   One helper, so every call handles a refusal the same way. The API answers
   every failure with {code, message} except a 413, which Starlette refuses
   before the application exists. */
/* Status 0, which no HTTP response carries, so a caller can tell "we never got
   an answer we can use" from any answer the server actually gave. */
function unreachable(message) {
  return { ok: false, status: 0, body: { code: "unreachable", message } };
}

export async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      headers: { "content-type": "application/json" },
      ...options,
    });
  } catch {
    // `fetch` REJECTS when the network is gone, where a REFUSED request
    // resolves. Caught HERE and not at each call site, because this helper
    // exists so every caller treats a failure the same way, and a rejection
    // that escapes lands in a click handler that has already rendered a
    // success: tapping Stop with the wifi off left "Waiting for it to finish"
    // on screen for a request that was never made. An error rendered as a
    // success is worse than no guard.
    return unreachable("The connection dropped.");
  }
  if (response.ok) {
    try {
      return { ok: true, status: response.status, body: await response.json() };
    } catch {
      // A 200 whose body does not arrive or does not parse. The connection
      // dropping AFTER the headers is the same wifi in a lift as above, and a
      // captive portal answering `200 text/html` is the other one. The server
      // refused nothing, so this is not a refusal, and it must not reach a
      // caller as a success carrying an undefined body.
      //
      // Reading the body was outside the catch when it was first written, so
      // `api` still rejected on this path while the comment below said it did
      // not, and removing `refresh`'s own catch on the strength of that made
      // the page keep asserting it was live when the listing had failed.
      //
      // The REAL status, not 0. We reached the server and it answered; what
      // failed was reading the answer. That is a different thing from never
      // having got one, and the listing turns the two into different words on
      // screen: "not live" sends somebody to look at their network, and this
      // one should not.
      return {
        ok: false,
        status: response.status,
        body: { code: "unreadable_answer", message: "The answer could not be read." },
      };
    }
  }
  let body = { code: "unreachable", message: response.statusText };
  try {
    body = await response.json();
  } catch {
    /* A 413 is text/plain, and so is anything a proxy inserts. */
  }
  return { ok: false, status: response.status, body };
}
