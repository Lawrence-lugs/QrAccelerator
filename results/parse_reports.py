import pandas as pd
import re
from typing import List, Dict, Optional, Tuple, Union
from matplotlib.ticker import EngFormatter
import seaborn as sns
import numpy as np
import matplotlib.pyplot as plt
sns.set_theme(style="whitegrid")

def plot_power_pie(df,startangle: int = 140):
    # Set a threshold for minimum percentage to show separately
    threshold = 1.0  # percent
    df_plot = df.copy()
    mask = df_plot['percentage'] < threshold

    # Group small percentages into 'Others'
    if mask.any():
        others = df_plot[mask].sum(numeric_only=True)
        others_row = {
            'hierarchy_clean': 'Others',
            'total_power': others['total_power'],
            'percentage': others['percentage']
        }
        df_plot = df_plot[~mask]
        df_plot = pd.concat([df_plot, pd.DataFrame([others_row])], ignore_index=True)

    fig, ax = plt.subplots(figsize=(8, 4), dpi=300)
    wedges, texts, autotexts = plt.pie(
        df_plot['total_power'],
        labels=df_plot['hierarchy_clean'],
        autopct='%1.1f%%',
        startangle=startangle,
        explode=[0.05]*len(df_plot),
        colors=sns.color_palette("viridis_r", len(df_plot)),
        pctdistance=1.2,
        labeldistance=2
    )

    # Rotate labels and percents to align with wedges
    for i, (w, t, a) in enumerate(zip(wedges, texts, autotexts)):
        ang = (w.theta2 + w.theta1) / 2
        # Set label rotation based on angle position
        if 90 <= (ang % 360) <= 270:
            # Left side: keep as is
            t.set_rotation(ang-180)
            t.set_va('center')
            t.set_ha('center')
            a.set_rotation(ang-180)
            a.set_va('center')
            a.set_ha('center')
        else:
            # Right side: subtract 180 for upside-down text
            t.set_rotation(ang)
            t.set_va('center')
            t.set_ha('center')
            a.set_rotation(ang)
            a.set_va('center')
            a.set_ha('center')


def plot_power_report(df: pd.DataFrame, output_file: str = None, ax: Optional[plt.Axes] = None):

    if ax is None:
        fig, ax = plt.subplots(figsize=(4, 2), dpi=300)

    sns.barplot(data=df, x='hierarchy_clean', y='total_power', palette='viridis', ax=ax)
    plt.yscale('log')
    plt.xticks(rotation=30, ha='right', rotation_mode='anchor')

    # Add engineering unit labels to y-axis
    ax.yaxis.set_major_formatter(EngFormatter(unit='W'))

    # Add value labels in engineering format
    eng_fmt = EngFormatter(unit='W', places=0)
    for p in ax.patches:
        height = p.get_height()
        if height > 0:
            ax.annotate(eng_fmt(height), (p.get_x() + p.get_width() / 2, height),
                        ha='center', va='bottom', fontsize=7, rotation=0)
            
    plt.xlabel('Block')
    plt.ylabel('Total Power (W)')

    if output_file:
        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        plt.close(fig)

def plot_area_report(df: pd.DataFrame, output_file: str = None, ax: Optional[plt.Axes] = None):
    """Plot area report data as a bar chart."""
    if ax is None:
        fig, ax = plt.subplots(figsize=(4, 2))

    sns.barplot(data=df, x='hierarchy_clean', y='total_area', palette='plasma', ax=ax)
    plt.yscale('log')
    plt.xticks(rotation=30, ha='right', rotation_mode='anchor')

    # Add value labels
    for p in ax.patches:
        height = p.get_height()
        if height > 0:
            ax.annotate(f'{height:.0f}', (p.get_x() + p.get_width() / 2, height),
                        ha='center', va='bottom', fontsize=7, rotation=0)
            
    plt.xlabel('Block')
    plt.ylabel('Total Area (µm²)')

    if output_file:
        plt.tight_layout()
        plt.savefig(output_file, dpi=300)
        plt.close(fig)


def plot_area_pie(df, startangle: int = 140):
    """Plot area report data as a pie chart."""
    # Set a threshold for minimum percentage to show separately
    threshold = 1.0  # percent
    df_plot = df.copy()
    mask = df_plot['percentage'] < threshold

    # Group small percentages into 'Others'
    if mask.any():
        others = df_plot[mask].sum(numeric_only=True)
        others_row = {
            'hierarchy_clean': 'Others', 
            'total_area': others['total_area'],
            'percentage': others['percentage']
        }
        df_plot = df_plot[~mask]
        df_plot = pd.concat([df_plot, pd.DataFrame([others_row])], ignore_index=True)

    # Add linebreaks for spaces in labels
    df_plot['label'] = df_plot['hierarchy_clean'].str.replace(' ', '\n')

    fig, ax = plt.subplots(figsize=(8, 4), dpi=300)
    wedges, texts, autotexts = plt.pie(
        df_plot['total_area'],
        labels=df_plot['label'],
        autopct='%1.1f%%',
        startangle=startangle,
        explode=[0.05]*len(df_plot),
        colors=sns.color_palette("viridis", len(df_plot)),
        pctdistance=1.2,
        labeldistance=2
    )

    # Rotate labels and percents to align with wedges  
    for i, (w, t, a) in enumerate(zip(wedges, texts, autotexts)):
        ang = (w.theta2 + w.theta1) / 2
        # Set label rotation based on angle position
        if 90 <= (ang % 360) <= 270:
            # Left side: keep as is
            t.set_rotation(ang-180)
            t.set_va('center')
            t.set_ha('center')
            a.set_rotation(ang-180)
            a.set_va('center')
            a.set_ha('center')
        else:
            # Right side: subtract 180 for upside-down text
            t.set_rotation(ang)
            t.set_va('center')
            t.set_ha('center')
            a.set_rotation(ang)
            a.set_va('center')
            a.set_ha('center')

    # plt.title('Area Distribution by Module')
    return fig


def parse_power_report(file_path: str, clean_names: bool = True) -> pd.DataFrame:
    """
    Parse a Synopsys power report file and return a pandas DataFrame.
    
    Args:
        file_path (str): Path to the power report file
        clean_names (bool): Whether to remove parentheses from hierarchy names
        
    Returns:
        pd.DataFrame: DataFrame containing parsed power data with columns:
                     - hierarchy: Module hierarchy path
                     - hierarchy_clean: Clean hierarchy path (without parentheses if clean_names=True)
                     - module_name: Base module name (extracted from hierarchy)
                     - instance_name: Instance name (extracted from hierarchy)
                     - switch_power: Switching power (mW)
                     - int_power: Internal power (mW)
                     - leak_power: Leakage power (uW)
                     - total_power: Total power (mW)
                     - percentage: Percentage of total power
                     - hierarchy_level: Depth in hierarchy (0 = top level)
    """
    
    data = []
    
    with open(file_path, 'r') as file:
        lines = file.readlines()
    
    # Find the start of the power data table
    table_start = None
    for i, line in enumerate(lines):
        if "Hierarchy" in line and "Power" in line:
            table_start = i + 2  # Skip the header and separator line
            break
    
    if table_start is None:
        raise ValueError("Could not find power data table in the file")
    
    # Parse each data line
    previous_line = ""
    previous_raw_line = ""
    for line_num, line in enumerate(lines[table_start:], start=table_start):
        line_raw = line  # Keep original line with spaces
        line_stripped = line.strip()
        
        # Skip empty lines and separator lines
        if not line_stripped or line_stripped.startswith('-') or 'Hierarchy' in line_stripped:
            continue
            
        # Stop if we reach the end of the table (indicated by a single number like "1")
        if re.match(r'^\d+\s*$', line_stripped):
            break

        # Check if the line is a continuation line (starts with spaces and then numbers)
        if line.startswith(' ') and re.match(r'^[\d.e-]+', line_stripped):
            if previous_line:
                # This line has the values for the previous line's hierarchy
                combined_line = previous_line + " " + line_stripped
                parsed_data = parse_power_line(combined_line, line_num, previous_raw_line, clean_names)
                if parsed_data:
                    data.append(parsed_data)
                previous_line = "" # Reset previous_line
                previous_raw_line = ""
            else:
                # This is a values line without a preceding hierarchy line, skip it
                continue
        else:
            # This line contains a hierarchy name. It might also contain values.
            parts = line_stripped.split()
            if len(parts) > 5 and any(char.isdigit() for char in parts[-1]):
                 # This is a single-line entry
                parsed_data = parse_power_line(line_stripped, line_num, line_raw, clean_names)
                if parsed_data:
                    data.append(parsed_data)
                previous_line = "" # Reset previous_line
                previous_raw_line = ""
            else:
                # This is the first line of a two-line entry, save it
                previous_line = line_stripped
                previous_raw_line = line_raw

    # Create DataFrame
    if not data:
        raise ValueError("No power data found in the file")
        
    df = pd.DataFrame(data)
    
    # Convert numeric columns to appropriate types
    numeric_columns = ['switch_power', 'int_power', 'leak_power', 'total_power', 'percentage', 'hierarchy_level']
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    df = scale_power_values(df)
    
    return df


def parse_power_line(line: str, line_num: int, raw_line: str = None, clean_names: bool = True) -> Optional[Dict]:
    """
    Parse a single line of power data.
    
    Args:
        line (str): Line containing power data
        line_num (int): Line number for error reporting
        raw_line (str): Original line with preserved spacing for hierarchy level calculation
        clean_names (bool): Whether to remove parentheses from hierarchy names
        
    Returns:
        dict: Parsed data or None if line couldn't be parsed
    """
    
    # Split the line into hierarchy part and power values
    # The power values are typically the last 5 numbers on the line
    parts = line.split()
    
    if len(parts) < 5:
        return None
    
    # Extract power values (last 5 parts: switch, int, leak, total, percentage)
    try:
        switch_power = convert_power_value(parts[-5])
        int_power = convert_power_value(parts[-4])
        leak_power = convert_power_value(parts[-3])
        total_power = convert_power_value(parts[-2])
        percentage = float(parts[-1])
    except (ValueError, IndexError):
        return None
    
    # Everything before the power values is the hierarchy
    hierarchy_parts = parts[:-5]
    hierarchy = ' '.join(hierarchy_parts)
    
    # Calculate hierarchy level based on leading spaces in the raw line
    if raw_line:
        # The hierarchy level is typically represented by the number of spaces.
        # Let's assume a simple model where more spaces mean deeper hierarchy.
        # A common indentation is 2 spaces per level.
        hierarchy_level = count_leading_spaces(raw_line) // 2
    else:
        hierarchy_level = 0
    
    # Clean hierarchy name if requested
    hierarchy_clean = clean_hierarchy_name(hierarchy, clean_names)
    
    # Extract module and instance names
    module_name, instance_name = extract_names(hierarchy)
    
    return {
        'hierarchy': hierarchy.strip(),
        'hierarchy_clean': hierarchy_clean,
        'module_name': module_name,
        'instance_name': instance_name,
        'switch_power': switch_power,
        'int_power': int_power,
        'leak_power': leak_power,
        'total_power': total_power,
        'percentage': percentage,
        'hierarchy_level': hierarchy_level,
        'line_number': line_num
    }

def scale_power_values(df: pd.DataFrame) -> pd.DataFrame:
    """
    Scale power values to proper units:
    - int_power, switch_power, total_power from mW to W (multiply by 1e-3)
    - leak_power from uW to W (multiply by 1e-6)
    
    Args:
        df (pd.DataFrame): Power data DataFrame
        
    Returns:
        pd.DataFrame: DataFrame with scaled power values
    """
    df_scaled = df.copy()
    df_scaled[['int_power', 'switch_power', 'total_power']] *= 1e-3
    df_scaled['leak_power'] *= 1e-6
    return df_scaled


def convert_numeric_value(value_str: str) -> float:
    """
    Convert numeric value string to float, handling scientific notation.
    
    Args:
        value_str (str): Numeric value string (e.g., "1.23e-02", "0.000")
        
    Returns:
        float: Converted numeric value
    """
    try:
        return float(value_str)
    except ValueError:
        # Handle special cases or return 0 for non-numeric values
        return 0.0


# Backward compatibility alias
convert_power_value = convert_numeric_value


def count_leading_spaces(line: str) -> int:
    """Count the number of leading spaces in a line."""
    return len(line) - len(line.lstrip(' '))


def clean_hierarchy_name(hierarchy: str, remove_parentheses: bool = True) -> str:
    """
    Clean hierarchy name by optionally removing parentheses and their contents.
    
    Args:
        hierarchy (str): Full hierarchy string
        remove_parentheses (bool): Whether to remove parentheses and their contents
        
    Returns:
        str: Cleaned hierarchy name
    """
    if remove_parentheses:
        # Remove everything within parentheses (including the parentheses)
        cleaned = re.sub(r'\s*\([^)]*\)', '', hierarchy)
        return cleaned.strip()
    else:
        return hierarchy.strip()


def extract_names(hierarchy: str) -> Tuple[str, str]:
    """
    Extract module name and instance name from hierarchy string.
    
    Args:
        hierarchy (str): Full hierarchy string
        
    Returns:
        tuple: (module_name, instance_name)
    """
    
    # Look for pattern like "instance_name (module_name_with_params)"
    match = re.search(r'([^(]+)\s*\(([^)]+)\)', hierarchy)
    
    if match:
        instance_name = match.group(1).strip()
        module_info = match.group(2).strip()
        
        # Extract base module name (remove parameters)
        module_name = module_info.split('_')[0] if '_' in module_info else module_info
        
        return module_name, instance_name
    else:
        # If no parentheses found, use the entire hierarchy as instance name
        return hierarchy.strip(), hierarchy.strip()


def analyze_power_data(df: pd.DataFrame) -> Dict:
    """
    Perform basic analysis on the power data.
    
    Args:
        df (pd.DataFrame): Power data DataFrame
        
    Returns:
        dict: Analysis results
    """
    
    analysis = {
        'total_modules': len(df),
        'total_power_mw': df['total_power'].sum(),
        'total_switch_power_mw': df['switch_power'].sum(),
        'total_int_power_mw': df['int_power'].sum(),
        'total_leak_power_uw': df['leak_power'].sum(),
        'top_power_consumers': df.nlargest(10, 'total_power')[['hierarchy', 'total_power', 'percentage']],
        'hierarchy_levels': df['hierarchy_level'].max() + 1,
        'power_by_hierarchy_level': df.groupby('hierarchy_level')['total_power'].sum(),
        'power_by_module_type': df.groupby('module_name')['total_power'].sum().sort_values(ascending=False)
    }
    
    return analysis


def export_analysis(df: pd.DataFrame, analysis: Dict, output_prefix: str = "power_analysis"):
    """
    Export analysis results to CSV and summary text files.
    
    Args:
        df (pd.DataFrame): Power data DataFrame
        analysis (dict): Analysis results
        output_prefix (str): Prefix for output files
    """
    
    # Export full DataFrame
    df.to_csv(f"{output_prefix}_full.csv", index=False)
    
    # Export top power consumers
    analysis['top_power_consumers'].to_csv(f"{output_prefix}_top_consumers.csv", index=False)
    
    # Export power by module type
    analysis['power_by_module_type'].to_csv(f"{output_prefix}_by_module.csv")
    
    # Export summary
    with open(f"{output_prefix}_summary.txt", 'w') as f:
        f.write("Power Analysis Summary\n")
        f.write("=====================\n\n")
        f.write(f"Total modules analyzed: {analysis['total_modules']}\n")
        f.write(f"Total power: {analysis['total_power_mw']:.3f} mW\n")
        f.write(f"Switch power: {analysis['total_switch_power_mw']:.3f} mW\n")
        f.write(f"Internal power: {analysis['total_int_power_mw']:.3f} mW\n")
        f.write(f"Leakage power: {analysis['total_leak_power_uw']:.3f} uW\n")
        f.write(f"Hierarchy levels: {analysis['hierarchy_levels']}\n\n")
        
        f.write("Top 10 Power Consumers:\n")
        f.write("-" * 50 + "\n")
        for idx, row in analysis['top_power_consumers'].iterrows():
            f.write(f"{row['hierarchy']}: {row['total_power']:.3f} mW ({row['percentage']:.1f}%)\n")


def parse_area_report(file_path: str, clean_names: bool = True) -> pd.DataFrame:
    """
    Parse a Synopsys area report file and return a pandas DataFrame.
    
    Args:
        file_path (str): Path to the area report file
        clean_names (bool): Whether to remove parentheses from hierarchy names
        
    Returns:
        pd.DataFrame: DataFrame containing parsed area data with columns:
                     - hierarchy: Module hierarchy path
                     - hierarchy_clean: Clean hierarchy path (without parentheses if clean_names=True)
                     - module_name: Base module name (extracted from hierarchy)
                     - instance_name: Instance name (extracted from hierarchy)
                     - total_area: Total area (absolute)
                     - percentage: Percentage of total area
                     - combi_area: Combinational area
                     - noncombi_area: Non-combinational area
                     - blackbox_area: Black box area
                     - hierarchy_level: Depth in hierarchy (0 = top level)
                     - design: Design name
    """
    
    data = []
    
    with open(file_path, 'r') as file:
        lines = file.readlines()
    
    # Find the start of the hierarchical area distribution table
    table_start = None
    for i, line in enumerate(lines):
        if "Hierarchical area distribution" in line:
            # Skip the header lines to find the actual data start
            for j in range(i + 1, len(lines)):
                if "Hierarchical cell" in lines[j]:
                    table_start = j + 2  # Skip the header and separator line
                    break
            break
    
    if table_start is None:
        raise ValueError("Could not find hierarchical area distribution table in the file")
    
    # Parse each data line
    previous_line = ""
    for line_num, line in enumerate(lines[table_start:], start=table_start):
        line_raw = line  # Keep original line with spaces
        line = line.strip()
        
        # Skip empty lines and separator lines
        if not line or line.startswith('-') or 'Hierarchical' in line:
            continue
            
        # Stop if we reach the end of the table (usually indicated by numbers only or empty line)
        if re.match(r'^\d+\s*$', line) or not line:
            break
            
        # Check if the line starts with numeric data (it's a continuation line)
        if re.match(r'^\d', line):
            if previous_line:
                # This line has the values for the previous line's hierarchy
                combined_line = previous_line + " " + line
                parsed_data = parse_area_line(combined_line, line_num, combined_line, clean_names)
                if parsed_data:
                    data.append(parsed_data)
                previous_line = "" # Reset previous_line
            else:
                # This is a values line without a preceding hierarchy line, skip it
                continue
        else:
            # This line contains a hierarchy name. It might also contain values.
            # Check if it also contains the numeric values.
            parts = line.split()
            if len(parts) > 1 and any(char.isdigit() for char in parts[-1]):
                 # This is a single-line entry
                parsed_data = parse_area_line(line, line_num, line_raw, clean_names)
                if parsed_data:
                    data.append(parsed_data)
                previous_line = "" # Reset previous_line
            else:
                # This is the first line of a two-line entry, save it
                previous_line = line.strip()

    # Create DataFrame
    if not data:
        raise ValueError("No area data found in the file")
        
    df = pd.DataFrame(data)
    
    # Convert numeric columns to appropriate types
    numeric_columns = ['total_area', 'percentage', 'combi_area', 'noncombi_area', 'blackbox_area', 'hierarchy_level']
    for col in numeric_columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    return df


def parse_area_line(line: str, line_num: int, raw_line: str = None, clean_names: bool = True) -> Optional[Dict]:
    """
    Parse a single line of area data.
    
    Args:
        line (str): Line containing area data
        line_num (int): Line number for error reporting
        raw_line (str): Original line with preserved spacing for hierarchy level calculation
        clean_names (bool): Whether to remove parentheses from hierarchy names
        
    Returns:
        dict: Parsed data or None if line couldn't be parsed
    """
    
    # Split the line into parts, but be careful about hierarchy names with spaces
    parts = line.split()
    
    if len(parts) < 6:
        return None
    
    # Extract area values - format is typically:
    # hierarchy_name  total_area  percentage  combi_area  noncombi_area  blackbox_area  design_name
    try:
        # The last part is the design name, the 5 before that are numeric values.
        # The rest is the hierarchy. This is more robust for names with spaces.
        
        design = parts[-1]
        blackbox_area = convert_numeric_value(parts[-2])
        noncombi_area = convert_numeric_value(parts[-3])
        combi_area = convert_numeric_value(parts[-4])
        percentage = convert_numeric_value(parts[-5])
        total_area = convert_numeric_value(parts[-6])
        
        # Everything before the numeric values is the hierarchy
        hierarchy_parts = parts[:-6]
        hierarchy = ' '.join(hierarchy_parts)
        
    except (ValueError, IndexError):
        return None
    
    # Calculate hierarchy level based on hierarchy string
    hierarchy = hierarchy.strip()
    if hierarchy == 'qr_acc_top':
        hierarchy_level = 0
    else:
        hierarchy_level = hierarchy.count('/') + 1
    
    # Clean hierarchy name if requested
    hierarchy_clean = clean_hierarchy_name(hierarchy, clean_names)
    
    # Extract module and instance names
    module_name, instance_name = extract_names(hierarchy)
    
    return {
        'hierarchy': hierarchy.strip(),
        'hierarchy_clean': hierarchy_clean,
        'module_name': module_name,
        'instance_name': instance_name,
        'total_area': total_area,
        'percentage': percentage,
        'combi_area': combi_area,
        'noncombi_area': noncombi_area,
        'blackbox_area': blackbox_area,
        'design': design,
        'hierarchy_level': hierarchy_level,
        'line_number': line_num
    }


def analyze_area_data(df: pd.DataFrame) -> Dict:
    """
    Perform basic analysis on the area data.
    
    Args:
        df (pd.DataFrame): Area data DataFrame
        
    Returns:
        dict: Analysis results
    """
    
    analysis = {
        'total_modules': len(df),
        'total_area': df['total_area'].sum(),
        'total_combi_area': df['combi_area'].sum(),
        'total_noncombi_area': df['noncombi_area'].sum(),
        'total_blackbox_area': df['blackbox_area'].sum(),
        'top_area_consumers': df.nlargest(10, 'total_area')[['hierarchy', 'total_area', 'percentage']],
        'hierarchy_levels': df['hierarchy_level'].max() + 1,
        'area_by_hierarchy_level': df.groupby('hierarchy_level')['total_area'].sum(),
        'area_by_module_type': df.groupby('module_name')['total_area'].sum().sort_values(ascending=False)
    }
    
    return analysis


def export_area_analysis(df: pd.DataFrame, analysis: Dict, output_prefix: str = "area_analysis"):
    """
    Export area analysis results to CSV and summary text files.
    
    Args:
        df (pd.DataFrame): Area data DataFrame
        analysis (dict): Analysis results
        output_prefix (str): Prefix for output files
    """
    
    # Export full DataFrame
    df.to_csv(f"{output_prefix}_full.csv", index=False)
    
    # Export top area consumers
    analysis['top_area_consumers'].to_csv(f"{output_prefix}_top_consumers.csv", index=False)
    
    # Export area by module type
    analysis['area_by_module_type'].to_csv(f"{output_prefix}_by_module.csv")
    
    # Export summary
    with open(f"{output_prefix}_summary.txt", 'w') as f:
        f.write("Area Analysis Summary\n")
        f.write("====================\n\n")
        f.write(f"Total modules analyzed: {analysis['total_modules']}\n")
        f.write(f"Total area: {analysis['total_area']:.3f} µm²\n")
        f.write(f"Combinational area: {analysis['total_combi_area']:.3f} µm²\n")
        f.write(f"Non-combinational area: {analysis['total_noncombi_area']:.3f} µm²\n")
        f.write(f"Black box area: {analysis['total_blackbox_area']:.3f} µm²\n")
        f.write(f"Hierarchy levels: {analysis['hierarchy_levels']}\n\n")
        
        f.write("Top 10 Area Consumers:\n")
        f.write("-" * 50 + "\n")
        for idx, row in analysis['top_area_consumers'].iterrows():
            f.write(f"{row['hierarchy']}: {row['total_area']:.3f} µm² ({row['percentage']:.1f}%)\n")


# Generic functions that work for both power and area reports
def parse_report(file_path: str, report_type: str = 'auto', clean_names: bool = True) -> pd.DataFrame:
    """
    Parse a Synopsys report file (power or area) and return a pandas DataFrame.
    
    Args:
        file_path (str): Path to the report file
        report_type (str): Type of report ('power', 'area', or 'auto' to detect)
        clean_names (bool): Whether to remove parentheses from hierarchy names
        
    Returns:
        pd.DataFrame: DataFrame containing parsed report data
    """
    
    if report_type == 'auto':
        # Auto-detect report type by looking at file content
        with open(file_path, 'r') as file:
            content = file.read()
            if "Hierarchical area distribution" in content:
                report_type = 'area'
            elif "Hierarchy" in content and any(word in content for word in ["power", "Switch", "Internal", "Leakage"]):
                report_type = 'power'
            else:
                raise ValueError("Could not auto-detect report type. Please specify 'power' or 'area'.")
    
    if report_type == 'power':
        return parse_power_report(file_path, clean_names)
    elif report_type == 'area':
        return parse_area_report(file_path, clean_names)
    else:
        raise ValueError("Report type must be 'power', 'area', or 'auto'")


def analyze_report_data(df: pd.DataFrame, report_type: str) -> Dict:
    """
    Perform analysis on report data (power or area).
    
    Args:
        df (pd.DataFrame): Report data DataFrame
        report_type (str): Type of report ('power' or 'area')
        
    Returns:
        dict: Analysis results
    """
    
    if report_type == 'power':
        return analyze_power_data(df)
    elif report_type == 'area':
        return analyze_area_data(df)
    else:
        raise ValueError("Report type must be 'power' or 'area'")


def export_report_analysis(df: pd.DataFrame, analysis: Dict, report_type: str, output_prefix: str = None):
    """
    Export report analysis results to CSV and summary text files.
    
    Args:
        df (pd.DataFrame): Report data DataFrame
        analysis (dict): Analysis results
        report_type (str): Type of report ('power' or 'area')
        output_prefix (str): Prefix for output files (defaults to "{report_type}_analysis")
    """
    
    if output_prefix is None:
        output_prefix = f"{report_type}_analysis"
    
    if report_type == 'power':
        export_analysis(df, analysis, output_prefix)
    elif report_type == 'area':
        export_area_analysis(df, analysis, output_prefix)
    else:
        raise ValueError("Report type must be 'power' or 'area'")


# Rename and maintain backward compatibility
export_analysis = export_analysis  # Keep original function name for power reports

if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python parse_reports.py <report_file> [report_type]")
        print("Example: python parse_reports.py synth/reports/power_qr_acc_top.txt power")
        print("Example: python parse_reports.py synth/reports/area_qr_acc_top.txt area")
        print("Example: python parse_reports.py synth/reports/power_qr_acc_top.txt auto")
        print("")
        print("report_type options:")
        print("  power - Parse as power report")
        print("  area  - Parse as area report") 
        print("  auto  - Auto-detect report type (default)")
        sys.exit(1)
    
    file_path = sys.argv[1]
    report_type = sys.argv[2] if len(sys.argv) > 2 else 'auto'
    
    try:
        # Parse the report
        print(f"Parsing report: {file_path}")
        df = parse_report(file_path, report_type)
        
        # Determine actual report type after parsing
        if 'total_power' in df.columns:
            actual_type = 'power'
            metric_col = 'total_power'
            metric_unit = 'W' if df[metric_col].max() < 1 else 'mW'
        elif 'total_area' in df.columns:
            actual_type = 'area'
            metric_col = 'total_area'
            metric_unit = 'µm²'
        else:
            raise ValueError("Could not determine report type from parsed data")
        
        print(f"Detected report type: {actual_type}")
        
        # Perform analysis
        print("Performing analysis...")
        analysis = analyze_report_data(df, actual_type)
        
        # Display summary
        print(f"\n{actual_type.title()} Analysis Summary:")
        print(f"Total modules: {analysis['total_modules']}")
        
        if actual_type == 'power':
            print(f"Total power: {analysis['total_power_mw']:.3f} mW")
            print(f"Switch power: {analysis['total_switch_power_mw']:.3f} mW")
            print(f"Internal power: {analysis['total_int_power_mw']:.3f} mW")
            print(f"Leakage power: {analysis['total_leak_power_uw']:.3f} µW")
            top_consumers = analysis['top_power_consumers']
        else:  # area
            print(f"Total area: {analysis['total_area']:.3f} µm²")
            print(f"Combinational area: {analysis['total_combi_area']:.3f} µm²")
            print(f"Non-combinational area: {analysis['total_noncombi_area']:.3f} µm²")
            print(f"Black box area: {analysis['total_blackbox_area']:.3f} µm²")
            top_consumers = analysis['top_area_consumers']
        
        print(f"Hierarchy levels: {analysis['hierarchy_levels']}")
        
        print(f"\nTop 5 {actual_type.title()} Consumers:")
        for idx, row in top_consumers.head().iterrows():
            print(f"  {row['hierarchy']}: {row[metric_col]:.3f} {metric_unit} ({row['percentage']:.1f}%)")
        
        # Export results
        print(f"\nExporting results...")
        export_report_analysis(df, analysis, actual_type)
        print("Analysis complete! Check the generated CSV and summary files.")
        
        # Display DataFrame info
        print(f"\nDataFrame shape: {df.shape}")
        print(f"Columns: {list(df.columns)}")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
