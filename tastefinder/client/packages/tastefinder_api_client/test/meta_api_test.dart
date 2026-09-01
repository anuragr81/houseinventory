import 'package:test/test.dart';
import 'package:tastefinder_api_client/tastefinder_api_client.dart';


/// tests for MetaApi
void main() {
  final instance = TastefinderApiClient().getMetaApi();

  group(MetaApi, () {
    // Health
    //
    // Liveness probe. The only endpoint in scope for Phase 1.
    //
    //Future<BuiltMap<String, String>> healthHealthGet() async
    test('test healthHealthGet', () async {
      // TODO
    });

  });
}
