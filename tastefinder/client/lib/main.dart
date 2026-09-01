// lib/main.dart
// -------------
// Phase 4 scope, per docs/00_BOOTSTRAP.md: one screen that calls GET /health
// through the generated client and displays the result. Nothing else --
// this proves the wiring end to end, and no more.

import 'package:flutter/material.dart';
import 'package:tastefinder_api_client/tastefinder_api_client.dart';

void main() {
  runApp(const TasteFinderApp());
}

class TasteFinderApp extends StatelessWidget {
  const TasteFinderApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Taste Platform',
      theme: ThemeData(colorSchemeSeed: Colors.deepPurple),
      home: const HealthCheckPage(),
    );
  }
}

sealed class HealthCheckState {
  const HealthCheckState();
}

class HealthCheckLoading extends HealthCheckState {
  const HealthCheckLoading();
}

class HealthCheckSuccess extends HealthCheckState {
  const HealthCheckSuccess(this.status);
  final String status;
}

class HealthCheckFailure extends HealthCheckState {
  const HealthCheckFailure(this.message);
  final String message;
}

class HealthCheckPage extends StatefulWidget {
  // Injectable so a test can supply a client backed by a fake Dio adapter
  // instead of a real network call -- see test/widget_test.dart. Production
  // code never passes this; it always falls back to the real client below.
  const HealthCheckPage({super.key, TastefinderApiClient? client})
      : _injectedClient = client;

  final TastefinderApiClient? _injectedClient;

  @override
  State<HealthCheckPage> createState() => _HealthCheckPageState();
}

class _HealthCheckPageState extends State<HealthCheckPage> {
  // The server's own /tastefinder mount, per wsgi.py. Overridable at build
  // time for pointing at a local dev server instead:
  //   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
  // 10.0.2.2 is the Android emulator's alias for the host machine's
  // localhost; a physical device needs the host's LAN address instead.
  static const _baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://research.anurags-econ.net/tastefinder',
  );

  late final TastefinderApiClient _client;
  HealthCheckState _state = const HealthCheckLoading();

  @override
  void initState() {
    super.initState();
    _client = widget._injectedClient ?? TastefinderApiClient(basePathOverride: _baseUrl);
    _checkHealth();
  }

  Future<void> _checkHealth() async {
    setState(() => _state = const HealthCheckLoading());
    try {
      final response = await _client.getMetaApi().healthHealthGet();
      if (!mounted) return;
      final status = response.data?['status'];
      setState(() {
        _state = status == null
            ? const HealthCheckFailure('Response had no status field')
            : HealthCheckSuccess(status);
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _state = HealthCheckFailure(error.toString()));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Taste Platform')),
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('Server: $_baseUrl', textAlign: TextAlign.center),
              const SizedBox(height: 24),
              switch (_state) {
                HealthCheckLoading() => const CircularProgressIndicator(),
                HealthCheckSuccess(:final status) => Column(
                    children: [
                      const Icon(Icons.check_circle, color: Colors.green, size: 48),
                      const SizedBox(height: 8),
                      Text('status: $status', style: Theme.of(context).textTheme.titleLarge),
                    ],
                  ),
                HealthCheckFailure(:final message) => Column(
                    children: [
                      const Icon(Icons.error, color: Colors.red, size: 48),
                      const SizedBox(height: 8),
                      Text(message, textAlign: TextAlign.center),
                    ],
                  ),
              },
              const SizedBox(height: 24),
              ElevatedButton(onPressed: _checkHealth, child: const Text('Retry')),
            ],
          ),
        ),
      ),
    );
  }
}
