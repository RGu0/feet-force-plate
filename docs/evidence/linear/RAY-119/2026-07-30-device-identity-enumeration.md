# RAY-119 read-only device-identity enumeration — 2026-07-30

## Purpose

Check whether the currently connected DO-P4864 can supply the stable physical
identity required before an engineering-selected dynamic mask may be bound to
it.  This is not a serial capture, acquisition, pressure, bad-point or load
test.

## Method

Only read-only macOS USB registry and pyserial enumeration were used.  The
serial port was not opened and no bytes were written.

## Sanitized result

* A CH340 candidate was present with VID:PID `1A86:7523` and product class
  `USB Serial`.
* The macOS USB descriptor reported `iSerialNumber=0`.
* pyserial reported no `serial_number` for the CH340 candidate.

## Conclusion and boundary

The attached board currently has no USB-provided stable serial identity that
the client can use to prove a physical-board binding.  The engineering binding
implementation therefore correctly refuses to associate an entered asset ID
with this connection.  Its port path, USB location, VID/PID and model are not
used as fallback identity because they can change or identify only a model/
host connection.

This evidence does not establish a bad point, a defect-free board, a load
result, calibration, or a completed RAY-119 deployment acceptance.  A future
accepted route needs a vendor-supported stable device identifier and deployed
identity-provider wiring, followed by an engineer's bind/reconnect/manual
distribution inspection.
