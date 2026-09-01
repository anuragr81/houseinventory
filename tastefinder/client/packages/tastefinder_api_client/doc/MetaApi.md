# tastefinder_api_client.api.MetaApi

## Load the API package
```dart
import 'package:tastefinder_api_client/api.dart';
```

All URIs are relative to *http://localhost*

Method | HTTP request | Description
------------- | ------------- | -------------
[**healthHealthGet**](MetaApi.md#healthhealthget) | **GET** /health | Health


# **healthHealthGet**
> BuiltMap<String, String> healthHealthGet()

Health

Liveness probe. The only endpoint in scope for Phase 1.

### Example
```dart
import 'package:tastefinder_api_client/api.dart';

final api = TastefinderApiClient().getMetaApi();

try {
    final response = api.healthHealthGet();
    print(response);
} catch on DioException (e) {
    print('Exception when calling MetaApi->healthHealthGet: $e\n');
}
```

### Parameters
This endpoint does not need any parameter.

### Return type

**BuiltMap&lt;String, String&gt;**

### Authorization

No authorization required

### HTTP request headers

 - **Content-Type**: Not defined
 - **Accept**: application/json

[[Back to top]](#) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to Model list]](../README.md#documentation-for-models) [[Back to README]](../README.md)

