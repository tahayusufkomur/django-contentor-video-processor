# -*- coding: utf-8 -*-
import fnmatch
import logging
import os
import shutil
import tempfile
import time

from django.conf import settings

from contentor_video_processor.models import get_s3_client
from django.core.files import File
from django.utils.functional import cached_property

from contentor_video_processor.storage import ResumableStorage


class ResumableFile(object):
    """
    Handles file saving and processing.
    It must only have access to chunk storage where it saves file chunks.
    When all chunks are uploaded it collects and merges them returning temporary file pointer
    that can be used to save the complete file to persistent storage.

    Chunk storage should preferably be some local storage to avoid traffic
    as files usually must be downloaded to server as chunks and re-uploaded as complete files.
    """

    def __init__(self, field, user, params):
        self.field = field
        self.user = user
        self.params = params
        self.chunk_suffix = "_part_"

    @cached_property
    def resumable_storage(self):
        return ResumableStorage()

    @cached_property
    def persistent_storage(self):
        return self.resumable_storage.get_persistent_storage()

    @cached_property
    def chunk_storage(self):
        return ResumableStorage().get_chunk_storage()

    @property
    def storage_filename(self):
        return self.resumable_storage.full_filename(self.filename, self.upload_to)

    @property
    def upload_to(self):
        return self.field.upload_to

    @property
    def chunk_exists(self):
        """
        Checks if the requested chunk exists.
        """
        return self.chunk_storage.exists(
            self.current_chunk_name
        ) and self.chunk_storage.size(self.current_chunk_name) == int(
            self.params.get("resumableCurrentChunkSize")
        )

    @property
    def chunk_names(self):
        """
        Iterates over all stored chunks.
        """
        chunks = []
        files = sorted(self.chunk_storage.listdir("")[1])
        for file in files:
            if fnmatch.fnmatch(file, "%s%s*" % (self.filename, self.chunk_suffix)):
                chunks.append(file)
        return chunks

    @property
    def current_chunk_name(self):
        # TODO: add user identifier to chunk name
        return "%s%s%s" % (
            self.filename,
            self.chunk_suffix,
            self.params.get("resumableChunkNumber").zfill(4),
        )

    def chunks(self):
        """
        Iterates over all stored chunks.
        """
        # TODO: add user identifier to chunk name
        files = sorted(self.chunk_storage.listdir("")[1])
        for file in files:
            if fnmatch.fnmatch(file, "%s%s*" % (self.filename, self.chunk_suffix)):
                yield self.chunk_storage.open(file, "rb").read()

    def delete_chunks(self):
        [self.chunk_storage.delete(chunk) for chunk in self.chunk_names]

    @property
    def file(self):
        """
        Merges file and returns its file pointer using optimized streaming.
        """
        if not self.is_complete:
            raise Exception("Chunk(s) still missing")

        # Create logging for monitoring large file operations
        logger = logging.getLogger('resumable_uploads')
        start_time = time.time()
        logger.info(f"Starting to merge {len(self.chunk_names)} chunks for file {self.filename}")

        # Use a larger buffer size (8MB) for better performance, especially on Windows
        buffer_size = 8 * 1024 * 1024  # 8MB buffer

        outfile = tempfile.NamedTemporaryFile("w+b")

        for i, chunk in enumerate(self.chunk_names):
            chunk_start = time.time()
            logger.info(f"Processing chunk {i + 1}/{len(self.chunk_names)}: {chunk}")

            with self.chunk_storage.open(chunk, 'rb') as chunk_file:
                # Use optimized copy with larger buffer
                shutil.copyfileobj(chunk_file, outfile, buffer_size)

            logger.info(f"Chunk {i + 1} processed in {time.time() - chunk_start:.2f} seconds")

        # Reset file pointer to beginning for reading
        outfile.seek(0)
        logger.info(f"All chunks merged in {time.time() - start_time:.2f} seconds")
        return outfile

    def file_already_exists(self):
        """
        Checks if a file with the same name and size already exists in S3 storage.
        """
        try:
            # Get S3 client
            client = get_s3_client(
                access_key=settings.__getattr__("AWS_ACCESS_KEY_ID"),
                secret_key=settings.__getattr__("AWS_SECRET_ACCESS_KEY"),
                endpoint_url=settings.__getattr__("AWS_S3_ENDPOINT_URL"),
            )

            # Extract bucket name and key from storage filename
            bucket_name = settings.__getattr__("AWS_STORAGE_BUCKET_NAME")

            # Apply AWS location prefix to the key if configured
            aws_location = settings.__getattr__("AWS_LOCATION")

            # Combine location prefix with storage filename to get the full key
            if aws_location and not self.storage_filename.startswith(aws_location):
                key = f"{aws_location.rstrip('/')}/{self.storage_filename}"
            else:
                key = self.storage_filename

            # Remove any double slashes that might have been created
            key = key.replace('//', '/')

            # Extract the expected file size
            total_size = int(self.params.get("resumableTotalSize"))

            print(f"Checking if file exists in S3: bucket={bucket_name}, key={key}")

            try:
                # Check if object exists and get its metadata
                response = client.head_object(Bucket=bucket_name, Key=key)

                # Get content length from response
                file_size = response.get('ContentLength', 0)

                print(f"Existing file found in S3: {key}, size: {file_size}, expected: {total_size}")

                # Compare sizes
                return file_size == total_size

            except client.exceptions.ClientError as e:
                # If the error code is 404, the object does not exist
                if e.response['Error']['Code'] == '404':
                    print(f"File does not exist in S3: {key}")
                    return False
                else:
                    # Other errors
                    print(f"Error checking file existence in S3: {str(e)}")
                    return False

        except Exception as e:
            print(f"Error in file_already_exists: {str(e)}")
            return False

    @property
    def filename(self):
        """
        Gets the filename.
        """
        # TODO: add user identifier to chunk name
        filename = self.params.get("resumableFilename")
        if "/" in filename:
            raise Exception("Invalid filename")
        value = "%s_%s" % (self.params.get("resumableTotalSize"), filename)
        return value

    @property
    def is_complete(self):
        """
        Checks if all chunks are already stored.
        """
        return int(self.params.get("resumableTotalSize")) == self.size

    def process_chunk(self, file):
        """
        Saves chunk to chunk storage.
        """
        print(f"Processing chunk: {self.current_chunk_name}")
        if self.chunk_storage.exists(self.current_chunk_name):
            print(f"Chunk already exists, deleting: {self.current_chunk_name}")
            self.chunk_storage.delete(self.current_chunk_name)
        self.chunk_storage.save(self.current_chunk_name, file)
        print(f"Chunk saved: {self.current_chunk_name}")

    @property
    def size(self):
        """
        Gets size of all chunks combined.
        """
        size = 0
        for chunk in self.chunk_names:
            size += self.chunk_storage.size(chunk)
        return size

    def collect(self):
        print(f"Starting file collection for {self.filename}")
        print(f"Total chunk count: {len(self.chunk_names)}")
        print(f"Chunk names: {self.chunk_names}")

        try:
            # Create a file object that uses our streaming property
            print("Calling file property to merge chunks...")
            file_obj = File(self.file)
            print(
                f"File object created successfully, size: {file_obj.size if hasattr(file_obj, 'size') else 'unknown'}")

            # Save to persistent storage with streaming
            print(f"Saving to persistent storage at path: {self.storage_filename}")
            actual_filename = self.persistent_storage.save(
                self.storage_filename, file_obj
            )
            print(f"File saved successfully as: {actual_filename}")

            # Clean up chunks after successful save
            print("Starting chunk cleanup...")
            self.delete_chunks()
            print("Chunk cleanup completed")

            print(f"Collection process completed successfully for {self.filename}")
            return actual_filename
        except Exception as e:
            print(f"Error during file collection: {str(e)}")
            print(f"Exception type: {type(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise  # Re-raise the exception after logging
