"""A scripted stand-in for the loaded Steamworks CDLL.

The manual-dispatch pump in pysteamnet._dispatch only ever touches five C
functions. None of the pump's correctness depends on a real Steam client:
it depends on *the exact order* in which those five functions are called
and on the bytes that flow through their pointers. So we test the pump
against this fake -- a tiny Python object that exposes those five
functions as attributes and replays a script of pre-baked events.

Why this works without any ctypes machinery on the fake's side: the pump
calls the library through plain Python attribute access
(`lib.SteamAPI_ManualDispatch_RunFrame(pipe)`), not through a ctypes
function prototype. A real CDLL would marshal the arguments; the fake
just receives the literal Python objects the pump passed -- the pipe int,
the `ctypes.byref(...)` pointer objects, the allocated arrays. That is
enough to (a) record every call in order and (b) write real bytes back
through the pointers exactly as Valve's library would.

THE SCRIPT

The constructor takes a list of events. Each event is one of two shapes:

    ("callback",   callback_id, payload_bytes)
        A plain broadcast callback. GetNextCallback will present a real
        CallbackMsg_t whose m_iCallback is callback_id and whose
        m_pubParam points at payload_bytes.

    ("callresult", handle, result_id, result_bytes, failed, fetch_ok)
        An async call completing. GetNextCallback presents a CallbackMsg_t
        carrying id 703 (SteamAPICallCompleted_t), whose INNER fields are
        (handle, result_id, len(result_bytes)). When the pump then calls
        GetAPICallResult, the fake copies result_bytes into the pump's
        buffer, sets pbFailed from `failed`, and returns `fetch_ok`.
        (fetch_ok == False models GetAPICallResult declining the result --
        the pump must deliver nothing for that event but still free it.)

THE CALL LOG

Every one of the five methods appends a tuple to self.call_log:
("RunFrame", ...), ("GetNextCallback", ...), ("FreeLastCallback", ...),
("GetAPICallResult", ...). The ordering tests read this log to assert
Valve's required call sequence -- the whole reason this fake exists.
"""

import ctypes

from pysteamnet._structs import CallbackMsg_t, SteamAPICallCompleted_t


class FakeSteamLib:
    """A scripted replacement for the loaded CDLL, for pump tests.

    Pass an instance to pysteamnet._dispatch.run_frame as ``lib=fake``.
    Then inspect ``fake.call_log`` to assert the call order.
    """

    def __init__(self, events):
        # The remaining events to hand out, oldest first. We pop from the
        # front as GetNextCallback is called; an empty list means the
        # frame is over and GetNextCallback returns 0 (false).
        self._events = list(events)

        # Every method call, in order, as ("ShortName", *args) tuples.
        self.call_log = []

        # The payload buffer backing the CallbackMsg_t we most recently
        # handed out. CallbackMsg_t.m_pubParam is a raw pointer into this
        # buffer, so the buffer must outlive the pointer -- we keep it
        # alive here until the next GetNextCallback (or FreeLastCallback).
        self._live_payload = None

    # -- the five manual-dispatch C functions, by their exact C names ----
    #
    # Real signatures (steam_api_internal.h), for reference:
    #   void SteamAPI_ManualDispatch_RunFrame(HSteamPipe)
    #   bool SteamAPI_ManualDispatch_GetNextCallback(HSteamPipe, CallbackMsg_t*)
    #   void SteamAPI_ManualDispatch_FreeLastCallback(HSteamPipe)
    #   bool SteamAPI_ManualDispatch_GetAPICallResult(HSteamPipe,
    #            SteamAPICall_t, void*, int, int, bool*)

    def SteamAPI_ManualDispatch_RunFrame(self, pipe):
        """Pump the underlying Steam frame. A no-op here beyond logging."""
        self.call_log.append(("RunFrame", pipe))

    def SteamAPI_ManualDispatch_GetNextCallback(self, pipe, pmsg):
        """Fill *pmsg with the next scripted event; return 1, or 0 if none.

        Writes a genuine CallbackMsg_t through the pointer so the pump
        reads it exactly as it would read Valve's. For a "callresult"
        event the payload presented is a real SteamAPICallCompleted_t
        (id 703) whose inner fields point the pump at the eventual
        result; the result bytes themselves are delivered later, by
        GetAPICallResult.
        """
        self.call_log.append(("GetNextCallback", pipe, pmsg))

        if not self._events:
            # No more events this frame. The pump's while-loop ends here;
            # by Valve's contract nothing else may run after a false
            # return, which the ordering tests check.
            return 0

        event = self._events.pop(0)
        kind = event[0]

        if kind == "callback":
            _, callback_id, payload_bytes = event
            self._present(pmsg, callback_id, payload_bytes)

        elif kind == "callresult":
            _, handle, result_id, result_bytes, failed, fetch_ok = event
            # Stash what GetAPICallResult will need when the pump calls it
            # for THIS event (it is always the very next thing the pump
            # does after seeing a 703).
            self._pending_result = {
                "handle": handle,
                "result_id": result_id,
                "result_bytes": result_bytes,
                "failed": failed,
                "fetch_ok": fetch_ok,
            }
            # The payload the pump sees for a 703 is the completion notice:
            # a real SteamAPICallCompleted_t whose inner fields describe
            # the result the pump must go fetch.
            completed = SteamAPICallCompleted_t()
            completed.m_hAsyncCall = handle
            completed.m_iCallback = result_id
            completed.m_cubParam = len(result_bytes)
            self._present(
                pmsg,
                SteamAPICallCompleted_t.k_iCallback,  # 703, the OUTER id
                bytes(completed),
            )

        else:
            raise ValueError(f"unknown scripted event kind: {kind!r}")

        return 1

    def SteamAPI_ManualDispatch_FreeLastCallback(self, pipe):
        """Release the slot the last GetNextCallback handed out."""
        self.call_log.append(("FreeLastCallback", pipe))
        # The real call invalidates m_pubParam; drop our backing buffer to
        # mirror that the bytes are no longer guaranteed to be alive.
        self._live_payload = None

    def SteamAPI_ManualDispatch_GetAPICallResult(
        self, pipe, hCall, pCallback, cub, iExpected, pbFailed
    ):
        """Copy the scripted result bytes into *pCallback; set *pbFailed.

        Records its arguments so the call-result test can assert the pump
        passed the INNER struct's handle/size/id (not the outer 703's),
        which is the Steamworks.NET-#413 regression class. Returns the
        scripted fetch_ok flag (a real GetAPICallResult returns false when
        it declines to hand over the result).
        """
        self.call_log.append(
            ("GetAPICallResult", pipe, hCall, pCallback, cub, iExpected, pbFailed)
        )

        result = self._pending_result
        # Set the failed-in-transit flag through the bool* the pump gave us.
        ctypes.cast(pbFailed, ctypes.POINTER(ctypes.c_bool))[0] = bool(result["failed"])

        if not result["fetch_ok"]:
            # Decline: the pump must deliver/store nothing for this event.
            return 0

        # Copy the result bytes into the pump's buffer. The pump sized that
        # buffer from the inner m_cubParam, so it is exactly len(result).
        payload = result["result_bytes"]
        ctypes.memmove(pCallback, payload, len(payload))
        return 1

    # -- internals -------------------------------------------------------

    def _present(self, pmsg, callback_id, payload_bytes):
        """Write a CallbackMsg_t carrying payload_bytes through pmsg.

        Keeps the payload buffer alive on the instance: CallbackMsg_t's
        m_pubParam is a raw pointer into it, and the pump dereferences
        that pointer before the next free.
        """
        # A mutable C buffer that outlives this call. A zero-length payload
        # still needs a real (1-byte) buffer to take a valid pointer from;
        # the pump won't read past m_cubParam == 0.
        n = len(payload_bytes)
        buf = (ctypes.c_uint8 * (n if n > 0 else 1))()
        if n > 0:
            ctypes.memmove(buf, payload_bytes, n)
        self._live_payload = buf  # keep alive until next free / next present

        msg = ctypes.cast(pmsg, ctypes.POINTER(CallbackMsg_t)).contents
        msg.m_hSteamUser = 1
        msg.m_iCallback = callback_id
        msg.m_pubParam = ctypes.cast(buf, ctypes.POINTER(ctypes.c_uint8))
        msg.m_cubParam = n
