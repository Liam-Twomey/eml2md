#import os
from pathlib import Path
import email
import shutil
import argparse
import re
import datetime
import binascii
import logging
from email.utils import parsedate_to_datetime
from email.header import decode_header


def decode_content(part):
    """Decode email part content based on its encoding."""
    content = part.get_payload(decode=True)
    charset = part.get_content_charset() or 'utf-8'

    try:
        return content.decode(charset)
    except UnicodeDecodeError:
        # Fallback to utf-8 if specified charset fails
        try:
            return content.decode('utf-8')
        except UnicodeDecodeError:
            # Last resort: ignore problematic characters
            return content.decode('utf-8', errors='ignore')


def decode_email_header(header):
    """Decode email header."""
    if header is None:
        return ""

    decoded_parts = []
    for content, encoding in decode_header(header):
        if isinstance(content, bytes):
            if encoding:
                try:
                    decoded_parts.append(content.decode(encoding))
                except (UnicodeDecodeError, LookupError):
                    # Fallback if specified encoding fails
                    decoded_parts.append(content.decode('utf-8', errors='ignore'))
            else:
                decoded_parts.append(content.decode('utf-8', errors='ignore'))
        else:
            decoded_parts.append(content)

    return "".join(decoded_parts)


def extract_email_parts(msg):
    """Extract relevant parts from an email message."""
    logger = logging.getLogger(__name__)

    # Extract headers
    date_str = msg.get('Date')
    date = None
    if date_str:
        try:
            date = parsedate_to_datetime(date_str)
        except:
            logger.warning(f"Failed to parse date: {date_str}")
            date = None

    from_addr = decode_email_header(msg.get('From', ''))
    to_addr = decode_email_header(msg.get('To', ''))
    cc_addr = decode_email_header(msg.get('Cc', ''))
    subject = decode_email_header(msg.get('Subject', ''))

    logger.debug(f"Extracting email: Subject='{subject}', From='{from_addr}'")

    # Extract body content and attachments
    body_text = ""
    attachments = []
    part_count = 0

    for part in msg.walk():
        part_count += 1
        content_type = part.get_content_type()
        content_disposition = part.get('Content-Disposition', '')

        # Handle text parts
        if content_type == 'text/plain' and 'attachment' not in content_disposition:
            logger.debug(f"  Part {part_count}: Extracting plain text content")
            body_text += decode_content(part)

        # Handle HTML parts if no plain text is available
        elif content_type == 'text/html' and 'attachment' not in content_disposition and not body_text:
            logger.debug(f"  Part {part_count}: Extracting HTML content (no plain text found)")
            # Basic HTML stripping (simple approach)
            html_content = decode_content(part)
            # Remove HTML tags (simple approach)
            body_text += re.sub(r'<[^>]+>', '', html_content)

        # Handle attachments
        elif 'attachment' in content_disposition or part.get_filename():
            filename = part.get_filename()
            if filename:
                filename = decode_email_header(filename)
                attachment_content = part.get_payload(decode=True)
                if attachment_content:
                    logger.debug(f"  Part {part_count}: Found attachment '{filename}' ({len(attachment_content)} bytes)")
                    attachments.append((filename, attachment_content, content_type))

    logger.info(f"Extracted email with {len(attachments)} attachment(s), body length: {len(body_text)} chars")

    return {
        'date': date,
        'from': from_addr,
        'to': to_addr,
        'cc': cc_addr,
        'subject': subject,
        'body': body_text,
        'attachments': attachments
    }


def extract_thread_parts(body_text):
    """
    Extract email thread parts from plain text body by identifying common
    email client quotation patterns.

    Returns a list of dictionaries containing extracted metadata and content for each part.
    """
    logger = logging.getLogger(__name__)
    thread_parts = []

    logger.debug("Searching for email thread patterns in body text")

    # Common patterns that indicate the start of a quoted email in the thread
    patterns = [
        # Common Outlook format
        r'From:[\s]*(.*?)[\r\n]+Sent:[\s]*(.*?)[\r\n]+To:[\s]*(.*?)(?:[\r\n]+Cc:[\s]*(.*?))?[\r\n]+Subject:[\s]*(.*?)[\r\n]+',
        # Alternative format sometimes seen
        r'On[\s]*(.*?),[\s]*(.*?)[\s]+wrote:[\r\n]+',
        # Gmail-style format
        r'On[\s]*(.*?)[\s]+at[\s]+(.*?),[\s]*(.*?)[\s]+wrote:[\r\n]+'
    ]

    # Find all occurrences of email headers in the body text
    for pattern in patterns:
        matches = list(re.finditer(pattern, body_text, re.IGNORECASE | re.DOTALL))
        if matches:
            logger.debug(f"Found {len(matches)} thread part(s) using pattern")
            last_end = 0
            for match in matches:
                # Extract metadata from the match
                if "From:" in pattern:
                    # Outlook format
                    email_part = {
                        'from': match.group(1).strip() if match.group(1) else "",
                        'date': match.group(2).strip() if match.group(2) else "",
                        'to': match.group(3).strip() if match.group(3) else "",
                        'cc': match.group(4).strip() if len(match.groups()) >= 4 and match.group(4) else "",
                        'subject': match.group(5).strip() if len(match.groups()) >= 5 and match.group(5) else "",
                        'body': ""  # Will be filled with content after the header
                    }
                else:
                    # Other formats
                    email_part = {
                        'from': match.group(3).strip() if len(match.groups()) >= 3 and match.group(3) else match.group(
                            1).strip(),
                        'date': match.group(1).strip() + " " + match.group(2).strip() if match.group(1) and match.group(
                            2) else "",
                        'to': "",
                        'cc': "",
                        'subject': "",
                        'body': ""
                    }

                # Find the end of this part (either the start of the next part or the end of the text)
                next_match = None
                for next_pattern in patterns:
                    next_match_iter = re.search(next_pattern, body_text[match.end():], re.IGNORECASE | re.DOTALL)
                    if next_match_iter:
                        next_match_start = match.end() + next_match_iter.start()
                        if next_match is None or next_match_start < next_match:
                            next_match = next_match_start

                if next_match is None:
                    email_part['body'] = body_text[match.end():].strip()
                else:
                    email_part['body'] = body_text[match.end():next_match].strip()

                thread_parts.append(email_part)

            # If we've found and processed parts with this pattern, we can stop checking other patterns
            if thread_parts:
                break

    if thread_parts:
        logger.info(f"Extracted {len(thread_parts)} email(s) from thread body")
    else:
        logger.debug("No thread patterns found in body text")

    return thread_parts


def simhash(text, num_bits=64):
    """
    Generate a SimHash fingerprint for text.

    Args:
        text: The text to hash
        num_bits: The number of bits in the hash

    Returns:
        An integer representing the SimHash fingerprint
    """
    # Clean and normalize the text
    text = re.sub(r'\s+', ' ', text.lower())

    # Extract features (we'll use words and bigrams)
    words = text.split()
    features = words + [' '.join(words[i:i + 2]) for i in range(len(words) - 1)]

    # Initialize vector for hash values
    v = [0] * num_bits

    # For each feature, compute hash and update vector
    for feature in features:
        # Use a consistent hash function
        h = binascii.crc32(feature.encode()) & 0xffffffff

        # Update the vector
        for i in range(num_bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1

    # Convert vector to binary fingerprint
    fingerprint = 0
    for i in range(num_bits):
        if v[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def hamming_distance(hash1, hash2):
    """
    Calculate the Hamming distance between two hashes.

    Args:
        hash1, hash2: Two integer hashes to compare

    Returns:
        The number of bit positions where the bits differ
    """
    xor = hash1 ^ hash2
    return bin(xor).count('1')


def email_feature_hash(email):
    """
    Create a fingerprint of an email for deduplication.

    Args:
        email: An email dictionary containing metadata and body

    Returns:
        A SimHash fingerprint of the email
    """
    # Extract the most important content for comparison
    content = ""

    # From field is very important
    if email.get('from'):
        content += email['from'] + " "

    # Subject is somewhat important
    if email.get('subject'):
        content += email['subject'] + " "

    # For the body, we'll extract key sentences
    body = email.get('body', '')

    # Extract the first few non-empty lines (typically the most distinctive)
    lines = [line.strip() for line in body.split('\n') if line.strip()]
    key_lines = lines[:min(5, len(lines))]

    # Add key lines to content
    content += " ".join(key_lines)

    # Generate SimHash
    return simhash(content)


def deduplicate_emails(emails, threshold=8):
    """
    Remove duplicate emails based on content similarity using SimHash.

    Args:
        emails: List of extracted email parts
        threshold: Maximum Hamming distance to consider as duplicate

    Returns:
        List of unique emails
    """
    logger = logging.getLogger(__name__)

    if not emails:
        return []

    logger.info(f"Deduplicating {len(emails)} email(s) with threshold={threshold}")

    # Normalize dates for comparison (handle timezone-aware vs timezone-naive)
    for email in emails:
        if isinstance(email.get('date'), datetime.datetime):
            # Convert to naive datetime if it's timezone-aware
            if email['date'].tzinfo is not None:
                # Convert to UTC and then remove timezone info
                email['date'] = email['date'].astimezone(datetime.timezone.utc).replace(tzinfo=None)

    # Calculate hashes for all emails
    logger.debug("Calculating SimHash fingerprints for all emails")
    email_hashes = [(email, email_feature_hash(email)) for email in emails]

    # Sort by date if available, to prioritize newer emails
    logger.debug("Sorting emails by date (newest first)")
    email_hashes.sort(
        key=lambda x: x[0].get('date') if isinstance(x[0].get('date'), datetime.datetime) else datetime.datetime.min,
        reverse=True
    )

    unique_emails = []
    used_indices = set()
    duplicates_found = 0

    # Iterate through emails
    logger.debug("Comparing emails for duplicates")
    for i, (email1, hash1) in enumerate(email_hashes):
        if i in used_indices:
            continue

        # Add this email to unique set
        unique_emails.append(email1)
        used_indices.add(i)

        # Mark similar emails as used
        for j, (email2, hash2) in enumerate(email_hashes):
            if j not in used_indices and j != i:
                # Calculate Hamming distance
                distance = hamming_distance(hash1, hash2)
                if distance <= threshold:
                    duplicates_found += 1
                    logger.debug(f"  Email {j} is duplicate of email {i} (distance={distance})")
                    used_indices.add(j)

    # Sort unique emails by date (already normalized)
    logger.info(f"Deduplication complete: {len(unique_emails)} unique, {duplicates_found} duplicate(s) removed")

    return unique_emails


def create_markdown_content(emails, newest_first=False):
    """Create markdown content from extracted email parts.

    Args:
        emails: List of extracted email parts
        newest_first: If True, sorts emails from newest to oldest. Default is oldest to newest.
    """
    # Note: We assume dates are already normalized before reaching this function

    # Sort emails by date
    sorted_emails = sorted(
        emails,
        key=lambda x: x['date'] if isinstance(x['date'], datetime.datetime) else datetime.datetime.min,
        reverse=newest_first  # Set to True for newest-first, False for oldest-first
    )

    markdown_content = "# Email Thread\n\n"

    for idx, email_parts in enumerate(sorted_emails, 1):
        markdown_content += f"## Email {idx}\n\n"

        # Add metadata
        if email_parts['date']:
            if isinstance(email_parts['date'], datetime.datetime):
                markdown_content += f"**Date**: {email_parts['date'].strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            else:
                markdown_content += f"**Date**: {email_parts['date']}\n\n"

        markdown_content += f"**From**: {email_parts['from']}\n\n"
        markdown_content += f"**To**: {email_parts['to']}\n\n"

        if email_parts['cc']:
            markdown_content += f"**CC**: {email_parts['cc']}\n\n"

        markdown_content += f"**Subject**: {email_parts['subject']}\n\n"

        # Add body content
        markdown_content += "### Content\n\n"
        markdown_content += email_parts['body'].strip() + "\n\n"

        # Add attachments info
        if email_parts.get('attachments') and email_parts['attachments']:
            markdown_content += "### Attachments\n\n"
            for attachment_name, _, _ in email_parts['attachments']:
                markdown_content += f"- [{attachment_name}]({attachment_name})\n"
            markdown_content += "\n"

        markdown_content += "---\n\n"

    return markdown_content


def process_eml_file(eml_file_path, newest_first=False):
    """Process an EML file and convert it to Markdown with attachments.

    Args:
        eml_file_path: Path to the EML file
        newest_first: If True, sorts emails from newest to oldest. Default is oldest to newest.
    """
    logger = logging.getLogger(__name__)

    # Import here to avoid circular imports
    import dateutil.parser
    
    output_dir = eml_file_path.parent/eml_file_path.stem
    logger.info(f"Processing: {eml_file_path.name}")

    # Create output directory name based on EML filename
    output_dir.mkdir(exist_ok=True)
    logger.debug(f"Output directory: {output_dir}")

    # Parse the EML file
    logger.debug(f"Parsing EML file: {eml_file_path}")
    with open(eml_file_path, 'rb') as file:
        msg = email.message_from_binary_file(file)

    # Initialize the emails list
    emails = []

    # First, try to extract embedded emails using the message/rfc822 method
    if msg.get_content_type() == 'multipart/mixed' and any(
            part.get_content_type() == 'message/rfc822' for part in msg.walk()):
        logger.info("Detected multipart message with embedded RFC822 emails")
        # This is a thread with forwarded messages
        # Extract the main email
        logger.debug("Extracting main email")
        main_email = extract_email_parts(msg)
        emails.append(main_email)

        # Extract embedded emails
        logger.debug("Extracting embedded emails")
        embedded_count = 0
        for part in msg.walk():
            if part.get_content_type() == 'message/rfc822':
                embedded_msgs = part.get_payload()
                if isinstance(embedded_msgs, list):
                    for embedded_msg in embedded_msgs:
                        embedded_count += 1
                        logger.debug(f"Extracting embedded email {embedded_count}")
                        emails.append(extract_email_parts(embedded_msg))
        logger.info(f"Extracted {embedded_count} embedded email(s)")
    else:
        logger.info("Processing as standard email (checking for thread patterns)")
        # Extract the main email parts
        logger.debug("Extracting main email")
        main_email = extract_email_parts(msg)
        emails.append(main_email)

        # Try to extract additional emails from the body text using pattern matching
        logger.debug("Searching for thread parts in body text")
        thread_parts = extract_thread_parts(main_email['body'])

        if thread_parts:
            logger.info(f"Processing {len(thread_parts)} thread part(s)")
            # If thread parts were found, append them to the emails list
            for idx, part in enumerate(thread_parts, 1):
                logger.debug(f"Processing thread part {idx}/{len(thread_parts)}")
                # Convert the date string to a datetime object if possible
                date_obj = None
                if part['date']:
                    try:
                        # Try common date formats
                        date_obj = dateutil.parser.parse(part['date'])
                        logger.debug(f"  Parsed date: {date_obj}")
                    except:
                        # If parsing fails, keep the string
                        logger.debug(f"  Could not parse date: {part['date']}")
                        date_obj = part['date']

                # Create an email entry for each thread part
                thread_email = {
                    'date': date_obj,
                    'from': part['from'],
                    'to': part['to'],
                    'cc': part['cc'],
                    'subject': part.get('subject', main_email['subject']),  # Use main subject if not found
                    'body': part['body'],
                    'attachments': []  # Thread parts typically don't have attachments
                }
                emails.append(thread_email)

    # Deduplicate emails using SimHash
    logger.info(f"Total emails found: {len(emails)}")
    unique_emails = deduplicate_emails(emails)

    # Deduplicate attachment filenames before saving
    logger.info("Deduplicating attachment filenames")
    used_filenames = {}  # Maps sanitized filename -> count
    for email_parts in unique_emails:
        if email_parts.get('attachments'):
            new_attachments = []
            for attachment_name, attachment_content, content_type in email_parts['attachments']:
                # Sanitize filename to avoid path issues
                safe_filename = Path(re.sub(r'[^\w\.-]', '_', attachment_name))

                # Check if this filename has been used before
                if safe_filename in used_filenames:
                    # Generate a unique filename by inserting a counter before the extension
                    used_filenames[safe_filename] += 1
                    unique_filename = f"{safe_filename.stem}_{used_filenames[safe_filename]}{safe_filename.suffix}"
                    logger.debug(f"  Renamed duplicate '{safe_filename}' to '{unique_filename}'")
                else:
                    used_filenames[safe_filename] = 0
                    unique_filename = safe_filename

                # Update the attachment tuple with the unique filename
                new_attachments.append((unique_filename, attachment_content, content_type))

            email_parts['attachments'] = new_attachments

    # Create markdown content (no need to normalize dates again, they're already normalized)
    sort_order = "newest to oldest" if newest_first else "oldest to newest"
    logger.info(f"Creating markdown content (sorted {sort_order})")
    markdown_content = create_markdown_content(unique_emails, newest_first)

    # Save markdown file
    md_file_path = output_dir/eml_file_path.with_suffix('.md')
    logger.info(f"Writing markdown file: {md_file_path}")
    with open(md_file_path, 'w', encoding='utf-8') as md_file:
        md_file.write(markdown_content)
    logger.debug(f"Markdown file written ({len(markdown_content)} bytes)")

    # Save attachments
    total_attachments = sum(len(email_parts.get('attachments', [])) for email_parts in unique_emails)
    if total_attachments > 0:
        logger.info(f"Saving {total_attachments} attachment(s)")
        attachment_count = 0
        for email_parts in unique_emails:
            for attachment_name, attachment_content, _ in email_parts.get('attachments', []):
                attachment_count += 1
                attachment_path = output_dir/attachment_name
                logger.debug(f"  [{attachment_count}/{total_attachments}] Saving: {attachment_name} ({len(attachment_content)} bytes)")

                with open(attachment_path, 'wb') as attachment_file:
                    attachment_file.write(attachment_content)
    else:
        logger.debug("No attachments to save")

    logger.info(f"Successfully processed: {eml_file_path.name}")
    return md_file_path


def main():
    """Main function to process all EML files in the input directory."""
    
    # Set up command line arguments
    parser = argparse.ArgumentParser(description='Convert EML files to Markdown format')
    parser.add_argument('--newest-first','-n', action='store_true',
                        help='Sort emails from newest to oldest (default: oldest to newest)')
    parser.add_argument('--dedup-threshold','-t', type=int, default=8,
                        help='Hamming distance threshold for deduplication (default: 8)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose debug logging')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Only show warnings and errors')
    parser.add_argument('filepaths',nargs="*",
                        help="Path to the .eml file(s)")
    args = parser.parse_args()

    # Configure logging
    log_level = logging.INFO
    if args.verbose:
        log_level = logging.DEBUG
    elif args.quiet:
        log_level = logging.WARNING

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting EML to Markdown converter")
    logger.info(f"Settings: newest_first={args.newest_first}, dedup_threshold={args.dedup_threshold}, filepaths={args.filepaths}")

    # Create required directories if they don't exist
    logger.debug("Creating required directories")
    fpaths = [Path(f) for f in args.filepaths]

    # Process all EML files in the input directory
    processed_files = []
    failed_files = []

    # Count total files first
    eml_files = [f for f in fpaths if f.suffix == '.eml']
    total_files = len(eml_files)

    if total_files == 0:
        logger.warning(f"No EML files supplied.")
        return

    logger.info(f"Processing {total_files} .eml files")
    logger.info("=" * 60)

    for idx, filename in enumerate(eml_files, 1):
        logger.info(f"[{idx}/{total_files}] Starting: {filename}")
        try:
            md_file_path = process_eml_file(filename, args.newest_first)
            processed_files.append((filename, md_file_path))
            logger.info(f"[{idx}/{total_files}] Success: {filename}")
        except Exception as e:
            logger.error(f"[{idx}/{total_files}] Failed: {filename} - {str(e)}", exc_info=args.verbose)
            failed_files.append((filename, str(e)))
        logger.info("-" * 60)

    # Print summary
    logger.info("=" * 60)
    logger.info("CONVERSION SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total files found: {total_files}")
    logger.info(f"Successfully processed: {len(processed_files)}")
    logger.info(f"Failed: {len(failed_files)}")

    if processed_files:
        logger.info("\nSuccessfully converted:")
        for original, converted in processed_files:
            logger.info(f"  {original} -> {converted}")

    if failed_files:
        logger.warning("\nFailed to convert:")
        for filename, error in failed_files:
            logger.warning(f"  {filename}: {error}")

if __name__ == "__main__":
    main()
