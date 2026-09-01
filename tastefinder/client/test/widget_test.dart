// test/widget_test.dart
// ----------------------
// The health screen calls a real server, so it is tested against a fake Dio
// adapter rather than a live one -- a real (or unreachable) network call
// leaves a Dio-internal Timer pending past pumpWidget, which flutter_test's
// binding treats as a leaked timer and fails the test, even when no code in
// this app touches it after disposal.

import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:tastefinder_api_client/tastefinder_api_client.dart';

import 'package:tastefinder/main.dart';

/// Answers every request with a canned response, synchronously -- no I/O,
/// no timers, nothing left pending when the test tears down.
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.statusCode, this.body);

  final int statusCode;
  final String body;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return ResponseBody.fromString(
      body,
      statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

TastefinderApiClient _clientReturning(int statusCode, String body) {
  final client = TastefinderApiClient(basePathOverride: 'http://localhost');
  client.dio.httpClientAdapter = _FakeAdapter(statusCode, body);
  return client;
}

void main() {
  testWidgets('shows the status returned by /health', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: HealthCheckPage(client: _clientReturning(200, '{"status":"ok"}')),
      ),
    );

    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pumpAndSettle();

    expect(find.text('status: ok'), findsOneWidget);
    expect(find.byIcon(Icons.check_circle), findsOneWidget);
  });

  testWidgets('shows a failure state when the server errors', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        home: HealthCheckPage(client: _clientReturning(500, 'boom')),
      ),
    );

    await tester.pumpAndSettle();

    expect(find.byIcon(Icons.error), findsOneWidget);
  });

  testWidgets('retry re-issues the health check', (WidgetTester tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: HealthCheckPage(client: _clientReturning(200, '{"status":"ok"}')),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('status: ok'), findsOneWidget);

    await tester.tap(find.text('Retry'));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.pumpAndSettle();
    expect(find.text('status: ok'), findsOneWidget);
  });
}
