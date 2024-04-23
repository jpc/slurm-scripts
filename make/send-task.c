// SPDX-FileCopyrightText: 2024 Jakub Piotr Cłapa <jpc@collabora.com>
// SPDX-License-Identifier: MIT

// send-task sends its command line to an HTTP endpoint and blocks until it gets a reply.
// It expects to be used as a SHELL in a Makefile to forward all the jobs to the job scheduler.
// This is an quick and dirty optimized implementation of send-task.py.

// FIXME: currently does not support passing in the cwd and the environment variables.

#define HTTP_IMPLEMENTATION
#include "http.h"
#include "cJSON.h"

int main( int argc, char** argv ) {
    char *payload = "";

    cJSON *spec = cJSON_CreateObject(); if (!spec) goto end;

    cJSON *args = cJSON_CreateArray(); if (!args) goto end;
    cJSON_AddItemToObject(spec, "argv", args);
    for(int i = 2; i < argc; i++) {
        cJSON *arg = cJSON_CreateString(argv[i]); if (!arg) goto end;
        cJSON_AddItemToArray(args, arg);
    }

    payload = cJSON_Print(spec);
    if (payload == NULL)
    {
        fprintf(stderr, "Failed to marshal payload.\n");
    }

end:
    cJSON_Delete(args);

    char url[1024];
    char *port = getenv("JOB_SCHEDULER_PORT");
    if (!port) port = "4444";
    snprintf(url, sizeof(url), "http://127.0.0.1:%s/", port);
    // the endpoint address has to be an IP to avoid getaddrinfo in static builds
    http_t* request = http_post(url, payload, strlen(payload), NULL );
    if( !request ) {
        printf( "Invalid request.\n" );
        return 1;
    }

    http_status_t status = HTTP_STATUS_PENDING;
    int prev_size = -1;
    while( status == HTTP_STATUS_PENDING ) {
        status = http_process( request );
        if( prev_size != (int) request->response_size ) {
            prev_size = (int) request->response_size;
        }
    }

    if( status == HTTP_STATUS_FAILED ) {
        printf( "HTTP request failed (%d): %s.\n", request->status_code, request->reason_phrase );
        http_release( request );
        return 1;
    }

    cJSON *json = cJSON_Parse((char const*)request->response_data);
    http_release( request );

    if (!json) {
        const char *error_ptr = cJSON_GetErrorPtr();
        if (error_ptr)
            fprintf(stderr, "Error before: %s\n", error_ptr);
        return 2;
    }
    cJSON *rc = cJSON_GetObjectItemCaseSensitive(json, "rc");
    if (!cJSON_IsNumber(rc)) return 2;

    return rc->valuedouble;
}
