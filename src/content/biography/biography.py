from datetime import datetime
import json
from typing import Dict, Optional, List
import uuid
import os
import asyncio
import re

class Section:
    def __init__(self, title: str, content: str = "", parent: Optional['Section'] = None):
        self.id = str(uuid.uuid4())
        self.title = title
        self.content = content
        self.created_at = datetime.now().isoformat()
        self.last_edit = datetime.now().isoformat()
        self.subsections: Dict[str, 'Section'] = {}
        self.memory_ids: List[str] = []
        self.update_memory_ids()

    def update_memory_ids(self) -> None:
        """Update memory_ids list by integrating IDs from content"""
        found_ids = self.extract_memory_ids(self.content)
        
        # Add new IDs without removing existing ones
        self.memory_ids.extend([id for id in found_ids if id not in self.memory_ids])

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "created_at": self.created_at,
            "last_edit": self.last_edit,
            "memory_ids": self.memory_ids,
            "subsections": {k: v.to_dict() for k, v in self.subsections.items()}
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'Section':
        section = cls(data["title"])
        section.id = data["id"]
        section.content = data["content"]
        section.created_at = data["created_at"]
        section.last_edit = data["last_edit"]
        section.memory_ids = data.get("memory_ids", [])
        section.subsections = {k: cls.from_dict(v) for k, v in data["subsections"].items()}
        return section

    @classmethod
    def extract_memory_ids(cls, content: str) -> List[str]:
        """Extract memory IDs from content text.
        
        Args:
            content: Text content that may contain memory IDs in [MEM_ID] format
            
        Returns:
            List[str]: List of unique memory IDs found in the content
            
        Example:
            >>> Section.extract_memory_ids("Text with [MEM_123] and [MEM_456]")
            ['MEM_123', 'MEM_456']
        """
        if not content:
            return []
            
        # Find all memory IDs in content using regex pattern [memory_id]
        pattern = r'\[(MEM_[\w-]+)\]'
        found_ids = re.findall(pattern, content)
        
        # Return unique IDs only
        return list(dict.fromkeys(found_ids))

class Biography:
    def __init__(self, user_id):
        # Path information
        self.user_id = user_id or str(uuid.uuid4())
        self.base_path = f"{os.getenv('DATA_DIR', 'data')}/{self.user_id}/"
        os.makedirs(self.base_path, exist_ok=True)

        # Version information
        self.version = self._get_next_version()
        self.file_name = f"{self.base_path}/biography_{self.version}"

        # Root section
        self.root = Section(f"Biography of {self.user_id}")

        # Locks for write operations
        self._write_lock = asyncio.Lock()           # Lock for write operations
        self._pending_writes = 0                    # Counter for pending write operations
        self._pending_writes_lock = asyncio.Lock()  # Lock for the counter
        self._all_writes_complete = asyncio.Event() # Event to track write completion
        self._all_writes_complete.set()             # Initially set to True

    async def _increment_pending_writes(self):
        """Increment the pending writes counter."""
        async with self._pending_writes_lock:
            self._pending_writes += 1
            self._all_writes_complete.clear()

    async def _decrement_pending_writes(self):
        """Decrement the pending writes counter."""
        async with self._pending_writes_lock:
            self._pending_writes -= 1
            if self._pending_writes == 0:
                self._all_writes_complete.set()

    def _get_next_version(self) -> int:
        """Get the next available version number for the biography file.
        
        Scans the directory for existing biography files and returns
        the next available version number.
        
        Example:
            If directory contains: biography_1.json, biography_2.json
            Returns: 3
        """
        # List all biography JSON files
        files = [f for f in os.listdir(self.base_path) 
                if f.startswith('biography_') and f.endswith('.json')]
        
        if not files:
            return 1
            
        # Extract version numbers from filenames
        versions = []
        for file in files:
            try:
                version = int(file.replace('biography_', '').replace('.json', ''))
                versions.append(version)
            except ValueError:
                continue
                
        next_version = max(versions) + 1 if versions else 1
        return next_version

    @classmethod
    def load_from_file(cls, user_id: str, version: int = -1) -> 'Biography':
        """Load a biography from file or create new one if it doesn't exist.
        
        Args:
            user_id: The ID of the user
            version: Optional specific version to load. If None, loads latest version.
        """
        biography = cls(user_id)
        
        if version > 0:
            # Load specific version
            file_path = f"{biography.base_path}/biography_{version}.json"
        else:
            # Use latest version (next version - 1)
            latest_version = biography._get_next_version() - 1
            if latest_version < 1:
                return biography
            file_path = f"{biography.base_path}/biography_{latest_version}.json"
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                biography.root = Section.from_dict(data)
                biography.version = version if version > 0 else latest_version
        except FileNotFoundError:
            pass
        
        return biography
    
    async def save(self, save_markdown: bool = False) -> None:
        """Save the biography to a JSON file using user_id."""
        try:
            # Wait for all pending writes with timeout
            await asyncio.wait_for(self._all_writes_complete.wait(), timeout=30)
        except asyncio.TimeoutError:
            raise TimeoutError("Timeout waiting for pending writes to complete")

        async with self._write_lock:
            os.makedirs(self.base_path, exist_ok=True)
            
            # Save JSON
            with open(f'{self.file_name}.json', 'w', encoding='utf-8') as f:
                json.dump(self.root.to_dict(), f, indent=4, ensure_ascii=False)

            # Save markdown if requested
            if save_markdown:
                self.export_to_markdown(save_to_file=True)

    def is_valid_path_format(self, path: str) -> bool:
        """
        Validate if the path follows the required format rules.
        Returns True if valid, False otherwise.
        """
        if not path:
            return True  # Empty path is valid (root)

        parts = path.split('/')
        
        # Check maximum depth
        if len(parts) > 3:
            return False
            
        # Validate first level requires single number prefix
        if not parts[0].split()[0].isdigit():
            return False
            
        # Validate second and third levels using _is_valid_subsection_number
        for i in range(1, len(parts)):
            if not self._is_valid_subsection_number(parts[i-1], parts[i]):
                return False
            
        return True

    def _is_valid_subsection_number(self, parent: str, child: str) -> bool:
        """
        Validate if subsection number matches parent section number.
        Examples:
            "1 Early Life" -> "1.1 Childhood" is valid
            "1.1 Childhood" -> "1.1.1 Details" is valid
        """
        try:
            parent_num = parent.split()[0]
            child_num = child.split()[0]
            
            # For second level (e.g., "1.1 Section")
            if parent_num.isdigit():
                return child_num.count('.') == 1 and child_num.startswith(f"{parent_num}.")
            
            # For third level (e.g., "1.1.1 Subsection")
            if '.' in parent_num:
                return child_num.count('.') == 2 and child_num.startswith(f"{parent_num}.")
            
            return False
        except (IndexError, ValueError):
            return False

    def _path_exists(self, path: str) -> bool:
        """
        Check if a given path exists in the biography.
        Returns True if the path exists, False otherwise.
        """
        if not self.is_valid_path_format(path):
            return False
        return self._get_section_by_path(path) is not None

    def _sort_sections(self, sections: Dict[str, Section]) -> Dict[str, Section]:
        """Sort sections based on their numeric prefixes."""
        def get_sort_key(title: str) -> tuple:
            # Split the title into parts (e.g., "1.2" from "1.2 Something")
            parts = title.split()[0].split('.')
            # Convert each numeric part to int for proper sorting
            return tuple(int(p) for p in parts if p.isdigit())

        # Sort sections by their numeric prefixes
        sorted_items = sorted(sections.items(), key=lambda x: get_sort_key(x[0]))
        return dict(sorted_items)

    def _find_parent(self, title: str) -> Optional[Section]:
        """Find the parent section of a section with the given title using DFS.
        
        Args:
            title: Title of the section whose parent we want to find
            
        Returns:
            Parent section if found, None if section is root or not found
        """
        def _search(section: Section) -> Optional[Section]:
            for subsection_title, subsection in section.subsections.items():
                if subsection_title == title:
                    return section
                parent = _search(subsection)
                if parent:
                    return parent
            return None
        
        return _search(self.root)
    
    def _get_section_by_path(self, path: str) -> Optional[Section]:
        """Get a section using its path (e.g., 'Chapter 1/Section 1.1')"""
        if not path:
            return self.root

        if path and not self.is_valid_path_format(path):
            raise ValueError(
                f"Invalid path format: {path}. "
                "Path must follow the required format rules."
            )

        current = self.root
        for part in path.split('/'):
            if part in current.subsections:
                current = current.subsections[part]
            else:
                return None
        return current

    def _get_section_by_title(self, title: str) -> Optional[Section]:
        """Find a section by its title using DFS"""
        def _search(section: Section) -> Optional[Section]:
            if section.title == title:
                return section
            for subsection in section.subsections.values():
                result = _search(subsection)
                if result:
                    return result
            return None
        
        return _search(self.root)
    
    def get_section(self, path: Optional[str] = None, title: Optional[str] = None, 
                   hide_memory_links: bool = True) -> Optional[Section]:
        """Get a section using either its path or title.
        
        Args:
            path: Path to the section
            title: Title of the section
            hide_memory_links: If True, removes memory ID brackets from content
        """
        section = None
        if path is None and title is None:
            raise ValueError("Must provide either path or title to get a section")
        elif path and title and not path.endswith(title):
            raise ValueError("Path and title must match to get a section")

        if path is not None:
            if not self.is_valid_path_format(path):
                raise ValueError(f"Invalid path format: {path}")
            section = self._get_section_by_path(path)
        else:
            section = self._get_section_by_title(title)

        if section and hide_memory_links:
            section.content = re.sub(r'\[([\w-]+)\]', '', section.content)
        
        return section

    def get_sections(self) -> Dict[str, Dict]:
        """Get a dictionary of all sections with their titles only"""
        def _build_section_dict(section: Section) -> Dict:
            return {
                "title": section.title,
                "subsections": {
                    k: _build_section_dict(v)
                    for k, v in section.subsections.items()
                }
            }
        
        return _build_section_dict(self.root)

    async def add_section(self, path: str, content: str = "") -> Section:
        """Add a new section at the specified path, creating parent sections if they don't exist."""
        await self._increment_pending_writes()
        try:
            async with self._write_lock:
                if not path:
                    raise ValueError("Path cannot be empty - must provide a section path")
                
                if not self.is_valid_path_format(path):
                    raise ValueError(
                        f"Invalid path format: {path}. "
                        "Path must follow the required format rules."
                    )

                # Split the path into parts
                path_parts = path.split('/')
                title = path_parts[-1]
                
                # Get or create the parent section
                current = self.root
                for part in path_parts[:-1]:
                    if part not in current.subsections:
                        new_parent = Section(part, "", current)
                        current.subsections[part] = new_parent
                    current = current.subsections[part]
                
                # Create and add the new section
                new_section = Section(title, content, current)
                current.subsections[path_parts[-1]] = new_section
                
                # Sort the subsections after adding the new one
                current.subsections = self._sort_sections(current.subsections)
                return new_section
        finally:
            await self._decrement_pending_writes()

    async def update_section(self, path: Optional[str] = None, title: Optional[str] = None, 
        content: Optional[str] = None, new_title: Optional[str] = None) -> Optional[Section]:
        """Update the content and optionally the title of a section by path or title."""
        await self._increment_pending_writes()
        try:
            async with self._write_lock:
                if path is None and title is None:
                    raise ValueError("Must provide either path or title")
                elif path and title and not path.endswith(title):
                    raise ValueError("Path and title must match to update a section")
                
                # Handle special case for root section
                if path is not None and path == "":
                    if content is not None:
                        self.root.content = content
                        self.root.last_edit = datetime.now().isoformat()
                    if new_title:
                        self.root.title = new_title
                    return self.root
                
                # Get section without hiding memory links to modify the original
                section = self.get_section(path=path, title=title, hide_memory_links=False)
                
                if section:
                    if content is not None:
                        section.content = content
                        section.last_edit = datetime.now().isoformat()
                        section.update_memory_ids()
                    
                    # Handle title update if provided
                    if new_title and new_title != section.title:
                        parent = self._find_parent(section.title)
                        if parent:
                            # Update the key in parent's subsections
                            subsections = parent.subsections
                            section = subsections.pop(section.title)
                            section.title = new_title  # Update the title
                            subsections[new_title] = section  # Add back with new title
                            # Sort the parent's subsections
                            parent.subsections = self._sort_sections(parent.subsections)
                        else:
                            # This is the root section
                            section.title = new_title
                    
                    return section
                return None
        finally:
            await self._decrement_pending_writes()
    
    async def delete_section(self, path: Optional[str] = None, title: Optional[str] = None) -> bool:
        """Delete a section by its path or title."""
        await self._increment_pending_writes()
        try:
            async with self._write_lock:
                if path is None and title is None:
                    raise ValueError("Must provide either path or title to delete a section")
                
                # Handle root section deletion attempt
                if path == "":
                    raise ValueError("Cannot delete root section")
                
                # Get section by path or title
                section = self.get_section(path=path, title=title)
                if section:
                    title = section.title
                
                if not section:
                    return False
                
                # Can't delete root section
                if section == self.root:
                    raise ValueError("Cannot delete root section")
                
                # Find and delete from parent's subsections
                parent = self._find_parent(section.title)
                if parent:
                    del parent.subsections[title]
                    return True
                
                return False
        finally:
            await self._decrement_pending_writes()

    def export_to_markdown(self, save_to_file: bool = False, 
                         hide_memory_links: bool = True) -> str:
        """Convert the biography to markdown format and optionally save to file.
        
        Args:
            save_to_file: Whether to save the markdown to a file
            hide_memory_links: If True, removes memory ID brackets from content
        """
        def _section_to_markdown(section: Section, level: int = 1) -> str:
            # Convert section to markdown with appropriate heading level
            md = f"{'#' * level} {section.title}\n\n"
            
            content = section.content
            if hide_memory_links:
                # Remove memory ID brackets from content
                content = re.sub(r'\[([\w-]+)\]', '', content)
                
            if content:
                md += f"{content}\n\n"
            
            # Process subsections recursively
            for subsection in section.subsections.values():
                md += _section_to_markdown(subsection, level + 1)
            
            return md

        # Generate markdown content
        markdown_content = _section_to_markdown(self.root)

        # Save to markdown file if requested
        if save_to_file:
            output_path = f"{self.file_name}.md"
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)

        return markdown_content
    
    @classmethod
    def export_to_markdown_from_file(cls, json_path: str, save_to_file: bool = True) -> str:
        """Convert a biography JSON file to markdown format and optionally save it.
        
        Args:
            json_path: Path to the biography JSON file
            save_to_file: Whether to save the markdown to a file (default: True)
            
        Returns:
            str: The generated markdown content
        """
        # Load and validate JSON file
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            root = Section.from_dict(data)
        except FileNotFoundError:
            raise FileNotFoundError(f"Biography file not found: {json_path}")
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON file: {json_path}")
        
        def _section_to_markdown(section: Section, level: int = 1) -> str:
            # Convert section to markdown with appropriate heading level
            md = f"{'#' * level} {section.title}\n\n"
            if section.content:
                md += f"{section.content}\n\n"
            
            # Process subsections recursively
            for subsection in section.subsections.values():
                md += _section_to_markdown(subsection, level + 1)
            
            return md

        # Generate markdown content
        markdown_content = _section_to_markdown(root)

        # Save to markdown file if requested
        if save_to_file:
            output_path = json_path.replace('.json', '.md')
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)

        return markdown_content

